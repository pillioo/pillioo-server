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

from openai import OpenAI
from sqlalchemy.orm import Session

from app.core.config import settings
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
    session_id가 주어지면 해당 세션을 조회 (없으면 404).
    session_id가 없으면 이 ticket의 기존 세션을 재사용하고,
    아직 세션이 없을 때만 새로 생성한다 (ticket당 세션 1개).
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
) -> ChatMessage:
    """
    chat_messages 테이블에 메시지 저장.
    """
    message = ChatMessage(
        ticket_id=ticket_id,
        session_id=session_id,
        role=role,
        content=content,
        retrieved_sources=retrieved_sources or [],
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


def build_ticket_state_summary(state: TicketState) -> str:
    """
    Summarizes routing-relevant TicketState fields so questions like
    "why was this routed this way?" can be answered without RAG.
    """
    lines = [
        f"status: {state.status.value if state.status else 'unknown'}",
        f"review_type: {state.review_type.value if state.review_type else 'not yet determined'}",
    ]
    if state.policy_decision:
        reasons = "; ".join(state.policy_decision.reasons) if state.policy_decision.reasons else "none"
        lines.append(f"policy_decision: {state.policy_decision.decision.value} (reasons: {reasons})")
    else:
        lines.append("policy_decision: not yet determined")
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
    약사 채팅 질의 처리.

    1. ticket 조회 -> TicketState 변환
    2. 세션 생성 또는 기존 세션 재사용 (ticket당 세션 1개)
    3. user 메시지 저장
    4. RetrievalService.retrieve() 호출 (recall_number_is_fallback 반영)
    5. 검색 결과 + 세션 히스토리 + ticket state 요약을 컨텍스트로 LLM 호출
       (evidence가 하나도 없으면 LLM을 부르지 않고 기존 fallback 메시지 유지)
    6. assistant 메시지 저장
    7. 응답 반환

    Args:
        db: DB 세션
        public_ticket_id: 공개 티켓 ID (e.g. "T-XXXX")
        user_query: 약사 질문
        session_id: 기존 세션 ID (없으면 ticket의 기존 세션을 재사용하거나 새로 생성)
        retrieval_service: RAG RetrievalService 인스턴스
        top_k: 검색 결과 수
        llm_client: OpenAI 호환 클라이언트 (테스트에서 주입 가능; 기본은 OpenAI())

    Returns:
        dict: session_id, answer, sources
    """
    ticket = get_ticket_by_public_id(db, public_ticket_id)
    state = ticket_to_state(db, ticket)

    session = get_or_create_session(db, ticket.id, session_id)

    save_message(
        db=db,
        ticket_id=ticket.id,
        session_id=session.session_id,
        role="user",
        content=user_query,
    )

    event = state.event_normalized
    # Do not use fallback event_id values as recall_number strong filters,
    # mirroring app.orchestration.steps.run_evidence_step.
    recall_number = None
    if event and not event.recall_number_is_fallback:
        recall_number = event.recall_number

    context = RetrievalContext(
        event_type=state.event_type.value if state.event_type else None,
        query=user_query,
        drug_name=event.drug_name if event else None,
        normalized_drug_name=resolve_retrieval_drug_name(event) if event else None,
        ndc=[event.ndc] if event and event.ndc else [],
        lot=event.lot if event else None,
        recall_number=recall_number,
        classification=state.classification.value if state.classification else None,
    )

    try:
        evidence_result = retrieval_service.retrieve(
            query=user_query,
            context=context,
            top_k=top_k,
        )
    except Exception:
        db.rollback()
        raise_review_error(
            ReviewError.INTERNAL_SERVER_ERROR,
            {"reason": "Evidence retrieval failed"}
        )

    sources = [
        {
            "source": chunk.source_path,
            "section": chunk.section,
            "score": round(chunk.score, 4),
            "content": chunk.content[:300],  # 미리보기 300자
        }
        for chunk in evidence_result.chunks[:top_k]
    ]

    if sources:
        history_messages = get_session_messages(db, session.session_id)
        state_summary = build_ticket_state_summary(state)
        chat_history_text = build_chat_history_context(history_messages)

        client = llm_client or OpenAI()
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
                answer = "죄송합니다. 응답을 생성하지 못했습니다."
        except Exception:
            db.rollback()
            raise_review_error(
                ReviewError.INTERNAL_SERVER_ERROR,
                {"reason": "Chat completion failed"}
            )
    else:
        # No evidence at all -- keep the original deterministic fallback
        # rather than letting the model answer ungrounded.
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

    return {
        "session_id": session.session_id,
        "answer": answer,
        "sources": sources,
    }


def get_chat_history(
    db: Session,
    public_ticket_id: str,
) -> list[dict]:
    """
    특정 티켓의 전체 채팅 기록 반환 (시간순).
    ticket당 세션이 하나이므로 ticket_id 기준 조회는 곧 그 세션의 전체 기록과 같다.
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
        }
        for msg in messages
    ]
