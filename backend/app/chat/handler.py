"""
Evidence Chat Handler

Handles pharmacist chat queries against a specific ticket's evidence context.
Calls RAG RetrievalService to find relevant evidence and an LLM to produce a
grounded, cited answer.

Pipeline position: after review payload is shown to pharmacist,
pharmacist can query evidence documents via chat.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.llm_client import build_llm_client
from app.chat.planner import (
    HYBRID,
    RETRIEVAL_REQUIRED,
    TICKET_STATE_ONLY,
    build_chat_plan,
    reformulate_followup_query,
)
from app.db.models.chat_model import ChatSession, ChatMessage
from app.orchestration.retrieval_identity import resolve_retrieval_drug_name
from app.orchestration.state import ticket_to_state
from app.rag.models import RetrievalContext
from app.rag.service import RetrievalService
from app.review.errors import ReviewError, raise_review_error
from app.review.tickets import get_ticket_by_public_id
from app.schemas.workflow import TicketState


_CHAT_SYSTEM_PROMPT = (
    "You are an evidence assistant helping a hospital pharmacist review a ticket. "
    "Answer the pharmacist's question using ONLY two sources of information: the ticket "
    "state summary below, and the retrieved evidence excerpts below. Never invent "
    "regulatory actions, procedures, or facts that are not present in either of those. "
    "When you rely on a retrieved evidence excerpt to support a claim, cite it inline, e.g. "
    '"(source: recall_sop.md, section: quarantine_procedure)". If neither the ticket state '
    "summary nor the evidence excerpts contain enough information to answer, say so plainly "
    "instead of guessing, and suggest the pharmacist consult the full ticket record. "
    "Keep the answer conservative and factual."
)

NO_EVIDENCE_FALLBACK_ANSWER = (
    "No relevant evidence found for your query. "
    "Please consult the pharmacist directly or broaden your search."
)


def get_or_create_session(
    db: Session,
    ticket_id: int,
    session_id: str | None,
) -> ChatSession:
    """
    session_id given: look up that session (404 if missing).
    session_id absent: reuse this ticket's existing session, creating one
    only if none exists yet (one session per ticket).
    """
    if session_id:
        session = db.query(ChatSession).filter(
            ChatSession.session_id == session_id,
            ChatSession.ticket_id == ticket_id,
        ).first()
        if not session:
            raise_review_error(
                ReviewError.REVIEW_NOT_FOUND,
                {"session_id": session_id, "reason": "Session not found"}
            )
        return session

    existing_session = (
        db.query(ChatSession)
        .filter(ChatSession.ticket_id == ticket_id)
        .order_by(ChatSession.created_at.asc())
        .first()
    )
    if existing_session:
        return existing_session

    session = ChatSession(
        session_id=str(uuid.uuid4()),
        ticket_id=ticket_id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(session)
    db.flush()
    db.refresh(session)
    return session


def save_message(
    db: Session,
    ticket_id: int,
    session_id: str,
    role: str,
    content: str,
    retrieved_sources: list[dict] | None = None,
    status: str = "succeeded",
) -> ChatMessage:
    """
    Persist a message into chat_messages.
    """
    message = ChatMessage(
        ticket_id=ticket_id,
        session_id=session_id,
        role=role,
        content=content,
        retrieved_sources=retrieved_sources or [],
        status=status,
        created_at=datetime.now(timezone.utc),
    )
    db.add(message)
    db.flush()
    db.refresh(message)
    return message


def get_session_messages(db: Session, session_id: str, limit: int = 10) -> list[ChatMessage]:
    """
    Recent chat history scoped to a single session (not the whole ticket),
    used to build prompt context for the next turn.
    """
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )
    return messages[-limit:]


def build_chat_history_context(messages: list[ChatMessage]) -> str:
    if not messages:
        return "(no earlier messages in this session)"
    return "\n".join(f"{message.role}: {message.content}" for message in messages)


def build_ticket_state_summary(state: TicketState, workflow_stage: str | None = None) -> str:
    """
    Summarizes routing-relevant TicketState fields so questions like
    "why was this routed this way?" can be answered without RAG.
    """
    event = state.event_normalized
    sufficiency = state.sufficiency_check
    impact = state.impact_summary
    inventory = state.inventory_result
    lines = [
        f"ticket_id: {state.ticket_id}",
        f"event_type: {state.event_type.value if state.event_type else 'unknown'}",
        f"drug_name: {event.drug_name if event else 'unknown'}",
        f"classification: {state.classification.value if state.classification else 'unknown'}",
        f"ndc: {event.ndc if event else 'unknown'}",
        f"lot: {event.lot if event and event.lot else 'unknown'}",
        f"recall_number: {event.recall_number if event and event.recall_number else 'unknown'}",
        f"status: {state.status.value if state.status else 'unknown'}",
        f"workflow_stage: {workflow_stage or 'unknown'}",
        f"review_type: {state.review_type.value if state.review_type else 'not yet determined'}",
    ]
    if inventory:
        lines.append(
            "inventory_result: "
            f"matched={inventory.matched}, match_type={inventory.match_type.value}, "
            f"match_confidence={inventory.match_confidence}, "
            f"needs_identity_review={inventory.needs_identity_review}"
        )
    else:
        lines.append("inventory_result: not yet run")
    if impact:
        departments = ", ".join(dept.value for dept in impact.affected_departments) or "none"
        breakdown = ", ".join(f"{dept.value}:{qty}" for dept, qty in impact.department_breakdown.items()) or "none"
        lines.append(
            "inventory_impact: "
            f"affected_departments={departments}, total_quantity={impact.total_quantity}, "
            f"department_breakdown={breakdown}, priority={impact.priority.value}, "
            f"urgent={impact.urgent}, urgent_reason={impact.urgent_reason or 'none'}"
        )
    else:
        lines.append("inventory_impact: not yet run")
    if sufficiency:
        lines.extend(
            [
                f"evidence_status: {sufficiency.evidence_status.value}",
                f"coverage_score: {sufficiency.coverage_score}",
                "missing_sources: "
                + (", ".join(source.value for source in sufficiency.missing_sources) or "none"),
                "weak_sources: "
                + (", ".join(source.value for source in sufficiency.weak_sources) or "none"),
                f"failure_reasons: {sufficiency.failure_reasons or 'none'}",
                f"citations_ready: {sufficiency.citations_ready}",
            ]
        )
    else:
        lines.extend(
            [
                "evidence_status: not yet run",
                "coverage_score: unknown",
                "missing_sources: unknown",
                "weak_sources: unknown",
                "failure_reasons: unknown",
                "citations_ready: unknown",
            ]
        )
    if state.policy_decision:
        reasons = "; ".join(state.policy_decision.reasons) if state.policy_decision.reasons else "none"
        lines.append(f"policy_decision: {state.policy_decision.decision.value} (reasons: {reasons})")
        lines.append(f"policy_routing_reason: {reasons}")
    else:
        lines.append("policy_decision: not yet determined")
        lines.append("policy_routing_reason: not yet determined")
    if state.safety_result:
        lines.append(
            f"safety_result: needs_action_review={state.safety_result.needs_action_review}, "
            f"blocked_sentences_count={len(state.safety_result.blocked_sentences)}"
        )
    else:
        lines.append("safety_result: not yet run")
    lines.append(f"draft_text: {state.draft_text or 'not yet generated'}")
    return "\n".join(lines)


def _build_chat_user_prompt(
    *,
    user_query: str,
    chat_history_text: str,
    state_summary: str,
    sources: list[dict],
) -> str:
    if sources:
        evidence_text = "\n".join(
            f"- source={item['source']} section={item['section']} score={item['score']}\n  {item['content']}"
            for item in sources
        )
    else:
        evidence_text = "(no evidence retrieved)"
    return (
        f"Conversation so far:\n{chat_history_text}\n\n"
        f"Ticket state summary:\n{state_summary}\n\n"
        f"Retrieved evidence:\n{evidence_text}\n\n"
        "When ticket state status and retrieved evidence scope differ, distinguish them clearly. "
        "For example, a ticket may have sufficient workflow evidence while the current retrieved "
        "sources only support the routing framework rather than product-specific facts.\n\n"
        f"Pharmacist question: {user_query}"
    )


def handle_chat(
    db: Session,
    public_ticket_id: str,
    user_query: str,
    session_id: str | None,
    retrieval_service: RetrievalService,
    top_k: int = 5,
    llm_client: object | None = None,
) -> dict:
    """
    Handle a pharmacist chat query.

    1. Look up ticket -> build TicketState
    2. Create or reuse the ticket's chat session (one session per ticket)
    3. Save the user message
    4. Call RetrievalService.retrieve() (honors recall_number_is_fallback)
    5. Call the LLM with retrieved evidence + session history + ticket state
       summary (if no evidence at all, skip the LLM and keep the existing
       fallback message)
    6. Save the assistant message
    7. Return the response

    Args:
        db: DB session
        public_ticket_id: public ticket id (e.g. "T-XXXX")
        user_query: pharmacist's question
        session_id: existing session id (if absent, reuse or create the
            ticket's session)
        retrieval_service: RAG RetrievalService instance
        top_k: number of retrieval results
        llm_client: OpenAI-compatible client (injectable in tests; defaults
            to build_llm_client())

    Returns:
        dict: session_id, answer, sources
    """
    ticket = get_ticket_by_public_id(db, public_ticket_id)
    state = ticket_to_state(db, ticket)

    session = get_or_create_session(db, ticket.id, session_id)
    # Commit the session immediately: a brand-new session must survive even
    # if something later in this turn fails (see the failure paths below).
    db.commit()

    # Fetch planning history BEFORE saving the current user message, so on
    # turn 1 it will be empty and reformulate_followup_query will correctly
    # short-circuit without making an LLM call (no prior context to resolve).
    planning_history = get_session_messages(db, session.session_id, limit=5)

    save_message(
        db=db,
        ticket_id=ticket.id,
        session_id=session.session_id,
        role="user",
        content=user_query,
    )
    # Commit the question immediately: it must not disappear if client
    # initialization, retrieval, or the LLM call fails below (previously
    # db.rollback() on those paths wiped out the just-saved session and
    # question, leaving zero DB trace of a failed turn).
    db.commit()

    # Build the LLM client after persisting the user question so that
    # initialization failures can be caught and persisted as failed assistant
    # messages rather than leaving no trace of the turn.
    try:
        client = llm_client or build_llm_client()
    except Exception:
        db.rollback()
        save_message(
            db=db,
            ticket_id=ticket.id,
            session_id=session.session_id,
            role="assistant",
            content="LLM client initialization failed for this question.",
            status="failed",
        )
        db.commit()
        raise_review_error(
            ReviewError.INTERNAL_SERVER_ERROR,
            {"reason": "LLM client initialization failed"}
        )
    # Best-effort: only attempt on genuine follow-ups (turn 2+), and never
    # let a condense failure block the chat turn -- falls back to the raw
    # last-message heuristic inside build_chat_plan/build_standalone_query.
    resolved_followup = reformulate_followup_query(
        user_query=user_query,
        recent_messages=planning_history,
        llm_client=client,
        model=settings.LLM_MODEL,
    )
    chat_plan = build_chat_plan(
        user_query=user_query,
        recent_messages=planning_history,
        state=state,
        resolved_followup=resolved_followup,
    )

    event = state.event_normalized
    # Do not use fallback event_id values as recall_number strong filters,
    # mirroring app.orchestration.steps.run_evidence_step.
    recall_number = None
    if event and not event.recall_number_is_fallback:
        recall_number = event.recall_number

    context = RetrievalContext(
        event_type=state.event_type.value if state.event_type else None,
        query=chat_plan.standalone_query,
        drug_name=event.drug_name if event else None,
        normalized_drug_name=resolve_retrieval_drug_name(event) if event else None,
        ndc=[event.ndc] if event and event.ndc else [],
        lot=event.lot if event else None,
        recall_number=recall_number,
        classification=state.classification.value if state.classification else None,
        target_profile=chat_plan.target_profile,
    )

    evidence_result = None
    sources: list[dict] = []
    if chat_plan.answer_mode != TICKET_STATE_ONLY:
        try:
            evidence_result = retrieval_service.retrieve(
                query=chat_plan.standalone_query,
                context=context,
                top_k=top_k,
            )
        except Exception:
            db.rollback()
            save_message(
                db=db,
                ticket_id=ticket.id,
                session_id=session.session_id,
                role="assistant",
                content="Evidence retrieval failed for this question.",
                status="failed",
            )
            db.commit()
            raise_review_error(
                ReviewError.INTERNAL_SERVER_ERROR,
                {"reason": "Evidence retrieval failed"}
            )

        sources = [
            {
                "source": chunk.source_path,
                "section": chunk.section,
                "score": round(chunk.score, 4),
                "content": chunk.content[:300],
            }
            for chunk in evidence_result.chunks[:top_k]
        ]

    if sources or chat_plan.answer_mode != RETRIEVAL_REQUIRED:
        history_messages = get_session_messages(db, session.session_id)
        state_summary = build_ticket_state_summary(state, workflow_stage=ticket.workflow_stage)
        chat_history_text = build_chat_history_context(history_messages)

        try:
            completion = client.chat.completions.create(
                model=settings.LLM_MODEL,
                messages=[
                    {"role": "system", "content": _CHAT_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": _build_chat_user_prompt(
                            user_query=user_query,
                            chat_history_text=chat_history_text,
                            state_summary=state_summary,
                            sources=sources,
                        ),
                    },
                ],
                temperature=0,
            )
            answer = completion.choices[0].message.content
            # Validate that the LLM response is not None or empty/whitespace-only
            if not answer or not answer.strip():
                answer = "Sorry, a response could not be generated."
        except Exception:
            db.rollback()
            save_message(
                db=db,
                ticket_id=ticket.id,
                session_id=session.session_id,
                role="assistant",
                content="Chat completion failed for this question.",
                retrieved_sources=sources,
                status="failed",
            )
            db.commit()
            raise_review_error(
                ReviewError.INTERNAL_SERVER_ERROR,
                {"reason": "Chat completion failed"}
            )
    else:
        # No evidence for a retrieval-required question -- keep the deterministic
        # fallback rather than letting the model answer ungrounded.
        answer = NO_EVIDENCE_FALLBACK_ANSWER

    save_message(
        db=db,
        ticket_id=ticket.id,
        session_id=session.session_id,
        role="assistant",
        content=answer,
        retrieved_sources=sources,
    )

    db.commit()

    evidence_status = None
    if evidence_result:
        evidence_status = evidence_result.sufficiency.evidence_status
    elif state.sufficiency_check:
        evidence_status = state.sufficiency_check.evidence_status.value
    answer_support_level = _answer_support_level(
        answer_mode=chat_plan.answer_mode,
        sources=sources,
        evidence_status=evidence_status,
    )

    return {
        "session_id": session.session_id,
        "answer": answer,
        "sources": sources,
        "intent": chat_plan.intent,
        "standalone_query": chat_plan.standalone_query,
        "answer_mode": chat_plan.answer_mode,
        "target_profile": chat_plan.target_profile,
        "evidence_status": evidence_status,
        "retrieved_evidence_scope": chat_plan.retrieved_evidence_scope,
        "answer_support_level": answer_support_level,
    }


def _answer_support_level(*, answer_mode: str, sources: list[dict], evidence_status: str | None) -> str:
    if answer_mode == TICKET_STATE_ONLY:
        return "state_only"
    if not sources:
        return "none"
    if answer_mode == HYBRID:
        return "partial"
    return "full" if evidence_status == "sufficient" else "partial"


def get_chat_history(
    db: Session,
    public_ticket_id: str,
) -> list[dict]:
    """
    Return the full chat history for a ticket (chronological order).
    Since there is one session per ticket, filtering by ticket_id is
    equivalent to returning that session's full history.
    """
    ticket = get_ticket_by_public_id(db, public_ticket_id)

    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.ticket_id == ticket.id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )

    return [
        {
            "ticket_id": ticket.ticket_id,
            "session_id": msg.session_id,
            "role": msg.role,
            "content": msg.content,
            "retrieved_sources": msg.retrieved_sources or [],
            "created_at": msg.created_at,
            "status": msg.status,
        }
        for msg in messages
    ]
