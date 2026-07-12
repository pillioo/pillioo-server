from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker


# JSONB has no sqlite compiler by default; map it to plain JSON so the real
# ORM models can run against an in-memory sqlite DB for these tests instead
# of requiring a live Postgres instance.
@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json_for_sqlite(element, compiler, **kw):
    return "JSON"


from app.db.base import Base
from app.db.models.approval_model import Approval  # noqa: F401
from app.db.models.audit_log_model import AuditLog  # noqa: F401
from app.db.models.chat_model import ChatMessage, ChatSession
from app.db.models.report_version_model import ReportVersion  # noqa: F401
from app.db.models.ticket import Ticket

from app.chat.handler import (
    NO_EVIDENCE_FALLBACK_ANSWER,
    build_ticket_state_summary,
    get_or_create_session,
    get_session_messages,
    handle_chat,
)
from app.chat.planner import _CONDENSE_SYSTEM_PROMPT
from app.rag.models import EvidenceResult as RagEvidenceResult
from app.rag.models import EvidencePlan, EvidenceTarget, RetrievalContext, SufficiencyResult


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def make_ticket(db_session, **overrides) -> Ticket:
    defaults = dict(
        ticket_id="T-CHAT-001",
        status="REVIEW_ROUTED",
        workflow_stage="PENDING_REVIEW",
        event_type="recall",
        drug_name="midazolam",
        ndc="00641601441",
        lot="LOT-A",
        classification="class_i",
        recall_number="FALLBACK-EVENT-ID-123",
        recall_number_is_fallback=True,
        reason_for_recall="Subpotent drug product",
        product_description="Midazolam HCl Injection 1 mg/mL vial",
        source_status="ongoing",
    )
    defaults.update(overrides)
    ticket = Ticket(**defaults)
    db_session.add(ticket)
    db_session.commit()
    db_session.refresh(ticket)
    return ticket


class FakeEvidenceService:
    def __init__(self, chunks=None):
        self.calls = []
        self._chunks = chunks if chunks is not None else []

    def retrieve(self, *, query, context=None, top_k=5, filter_override=None):
        self.calls.append({"query": query, "context": context, "top_k": top_k})
        plan = EvidencePlan(event_type="recall", targets=[EvidenceTarget("sop")])
        sufficiency = SufficiencyResult(
            required_document_types=["sop"],
            found_document_types=["sop"] if self._chunks else [],
            missing_document_types=[] if self._chunks else ["sop"],
            weak_document_types=[],
            coverage_score=1.0 if self._chunks else 0.0,
            evidence_status="sufficient" if self._chunks else "insufficient",
            needs_evidence_review=not bool(self._chunks),
            citations_ready=True,
        )
        return RagEvidenceResult(
            query=query,
            context=context or RetrievalContext(),
            plan=plan,
            chunks=self._chunks,
            sufficiency=sufficiency,
        )


class FakeChatCompletionMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class FakeChatChoice:
    def __init__(self, content: str) -> None:
        self.message = FakeChatCompletionMessage(content)


class FakeChatCompletions:
    def __init__(
        self,
        answer: str,
        condense_response: str | None = None,
        fail_condense: bool = False,
        fail_answer: bool = False,
    ) -> None:
        self.answer = answer
        self.condense_response = condense_response
        self.fail_condense = fail_condense
        self.fail_answer = fail_answer
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        is_condense_call = kwargs["messages"][0]["content"] == _CONDENSE_SYSTEM_PROMPT
        if is_condense_call:
            if self.fail_condense:
                raise RuntimeError("condense call failed")
            if self.condense_response is not None:
                return SimpleNamespace(choices=[FakeChatChoice(self.condense_response)])
            return SimpleNamespace(choices=[FakeChatChoice(self.answer)])
        if self.fail_answer:
            raise RuntimeError("chat completion failed")
        return SimpleNamespace(choices=[FakeChatChoice(self.answer)])


class FakeLLMClient:
    def __init__(
        self,
        answer: str = "Grounded answer (source: sop.md, section: procedure)",
        condense_response: str | None = None,
        fail_condense: bool = False,
        fail_answer: bool = False,
    ) -> None:
        self.completions = FakeChatCompletions(answer, condense_response, fail_condense, fail_answer)
        self.chat = SimpleNamespace(completions=self.completions)


class FailingEvidenceService:
    def retrieve(self, *, query, context=None, top_k=5, filter_override=None):
        raise RuntimeError("retrieval backend unavailable")


def chunk(**overrides):
    from app.rag.models import EvidenceChunk as RagEvidenceChunk

    defaults = dict(
        chunk_id="chunk-1",
        chunk_index=0,
        content="Quarantine affected lots pending pharmacist review per SOP 4.2.",
        document_id="doc-1",
        document_type="sop",
        event_type="recall",
        section="procedure",
        source_path="sop.md",
        score=0.9,
    )
    defaults.update(overrides)
    return RagEvidenceChunk(**defaults)


def test_get_or_create_session_reuses_existing_session_for_ticket(db_session):
    ticket = make_ticket(db_session)

    first = get_or_create_session(db_session, ticket.id, session_id=None)
    db_session.commit()
    second = get_or_create_session(db_session, ticket.id, session_id=None)

    assert first.session_id == second.session_id
    assert db_session.query(ChatSession).filter(ChatSession.ticket_id == ticket.id).count() == 1


def test_get_or_create_session_still_supports_explicit_session_id(db_session):
    ticket = make_ticket(db_session)
    created = get_or_create_session(db_session, ticket.id, session_id=None)
    db_session.commit()

    fetched = get_or_create_session(db_session, ticket.id, session_id=created.session_id)

    assert fetched.session_id == created.session_id


def test_handle_chat_drops_fallback_recall_number_from_retrieval_context(db_session):
    ticket = make_ticket(db_session)  # recall_number_is_fallback=True
    evidence_service = FakeEvidenceService(chunks=[chunk()])
    llm_client = FakeLLMClient()

    handle_chat(
        db=db_session,
        public_ticket_id=ticket.ticket_id,
        user_query="What does the SOP say?",
        session_id=None,
        retrieval_service=evidence_service,
        llm_client=llm_client,
    )

    assert len(evidence_service.calls) == 1
    context = evidence_service.calls[0]["context"]
    # recall_number_is_fallback=True must never be used as a strong filter.
    assert context.recall_number is None


def test_handle_chat_uses_real_recall_number_when_not_fallback(db_session):
    ticket = make_ticket(db_session, recall_number="D-REAL-2026-001", recall_number_is_fallback=False)
    evidence_service = FakeEvidenceService(chunks=[chunk()])
    llm_client = FakeLLMClient()

    handle_chat(
        db=db_session,
        public_ticket_id=ticket.ticket_id,
        user_query="What does the SOP say?",
        session_id=None,
        retrieval_service=evidence_service,
        llm_client=llm_client,
    )

    assert evidence_service.calls[0]["context"].recall_number == "D-REAL-2026-001"


def test_handle_chat_calls_llm_and_returns_grounded_answer_with_sources(db_session):
    ticket = make_ticket(db_session)
    evidence_service = FakeEvidenceService(chunks=[chunk()])
    llm_client = FakeLLMClient(answer="Quarantine per SOP. (source: sop.md, section: procedure)")

    result = handle_chat(
        db=db_session,
        public_ticket_id=ticket.ticket_id,
        user_query="What does the SOP say?",
        session_id=None,
        retrieval_service=evidence_service,
        llm_client=llm_client,
    )

    assert result["answer"] == "Quarantine per SOP. (source: sop.md, section: procedure)"
    assert result["sources"]
    assert result["sources"][0]["source"] == "sop.md"
    assert len(llm_client.completions.calls) == 1
    prompt = llm_client.completions.calls[0]["messages"][1]["content"]
    assert "sop.md" in prompt
    # ticket state summary must be present so routing questions are answerable without RAG
    assert "status:" in prompt
    assert "review_type:" in prompt


def test_handle_chat_keeps_fallback_message_and_skips_llm_when_no_evidence(db_session):
    ticket = make_ticket(db_session)
    evidence_service = FakeEvidenceService(chunks=[])
    llm_client = FakeLLMClient()

    result = handle_chat(
        db=db_session,
        public_ticket_id=ticket.ticket_id,
        user_query="격리는 어떻게 해?",
        session_id=None,
        retrieval_service=evidence_service,
        llm_client=llm_client,
    )

    assert result["answer"] == NO_EVIDENCE_FALLBACK_ANSWER
    assert result["sources"] == []
    assert llm_client.completions.calls == []


def test_handle_chat_reuses_same_session_across_calls_without_session_id(db_session):
    ticket = make_ticket(db_session)
    evidence_service = FakeEvidenceService(chunks=[chunk()])
    llm_client = FakeLLMClient()

    first = handle_chat(
        db=db_session, public_ticket_id=ticket.ticket_id, user_query="q1",
        session_id=None, retrieval_service=evidence_service, llm_client=llm_client,
    )
    second = handle_chat(
        db=db_session, public_ticket_id=ticket.ticket_id, user_query="q2",
        session_id=None, retrieval_service=evidence_service, llm_client=llm_client,
    )

    assert first["session_id"] == second["session_id"]
    assert db_session.query(ChatSession).filter(ChatSession.ticket_id == ticket.id).count() == 1
    assert db_session.query(ChatMessage).filter(ChatMessage.ticket_id == ticket.id).count() == 4


def test_handle_chat_uses_llm_resolved_followup_in_standalone_query(db_session):
    """
    A multi-turn follow-up's standalone_query now uses the LLM-resolved,
    coreference-resolved question (via reformulate_followup_query) instead
    of just echoing the prior turn's raw message text.
    """
    ticket = make_ticket(db_session, recall_number="D-REAL-2026-001", recall_number_is_fallback=False)
    evidence_service = FakeEvidenceService(chunks=[chunk()])
    # Deliberately avoids repeating any word (including common ones like
    # "the") and avoids words already present in context_terms/intent_terms
    # (drug name, recall_number, "quarantine", "recall", "procedure", etc.),
    # since build_standalone_query's _dedupe_words removes any word that
    # already occurred earlier in the assembled query -- a phrase reusing
    # those words would get silently mangled and make this assertion brittle
    # for reasons unrelated to what's under test here.
    llm_client = FakeLLMClient(
        answer="Grounded answer (source: sop.md, section: procedure)",
        condense_response="Should pharmacists isolate affected inventory pending disposal instructions?",
    )

    first = handle_chat(
        db=db_session,
        public_ticket_id=ticket.ticket_id,
        user_query="이 리콜에서 ICU 영향 있어?",
        session_id=None,
        retrieval_service=evidence_service,
        llm_client=llm_client,
    )
    second = handle_chat(
        db=db_session,
        public_ticket_id=ticket.ticket_id,
        user_query="그럼 격리는 어떻게 해?",
        session_id=first["session_id"],
        retrieval_service=evidence_service,
        llm_client=llm_client,
    )

    assert second["intent"] == "recall_action"
    assert second["answer_mode"] == "retrieval_required"
    assert second["target_profile"] == "recall_action"
    assert "Should pharmacists isolate affected inventory pending disposal instructions?" in second["standalone_query"]
    # Current turn's raw query is always appended verbatim regardless of the
    # resolved follow-up.
    assert "그럼 격리는 어떻게 해?" in second["standalone_query"]
    assert "midazolam" in second["standalone_query"]
    assert "D-REAL-2026-001" in second["standalone_query"]
    assert evidence_service.calls[-1]["query"] == second["standalone_query"]
    assert evidence_service.calls[-1]["context"].target_profile == "recall_action"

    condense_calls = [
        call for call in llm_client.completions.calls
        if call["messages"][0]["content"] == _CONDENSE_SYSTEM_PROMPT
    ]
    assert len(condense_calls) == 1
    condense_prompt = condense_calls[0]["messages"][1]["content"]
    assert "이 리콜에서 ICU 영향 있어?" in condense_prompt
    assert "그럼 격리는 어떻게 해?" in condense_prompt


def test_handle_chat_skips_condense_call_on_first_turn(db_session):
    """No prior history on the first turn -- reformulate_followup_query
    should short-circuit without making an LLM call at all."""
    ticket = make_ticket(db_session)
    evidence_service = FakeEvidenceService(chunks=[chunk()])
    llm_client = FakeLLMClient()

    handle_chat(
        db=db_session,
        public_ticket_id=ticket.ticket_id,
        user_query="이 리콜에서 ICU 영향 있어?",
        session_id=None,
        retrieval_service=evidence_service,
        llm_client=llm_client,
    )

    assert len(llm_client.completions.calls) == 1  # answer call only, no condense call


def test_handle_chat_falls_back_to_raw_message_when_condense_call_fails(db_session):
    """If the condense LLM call raises, chat must still succeed, falling
    back to the existing raw-last-message heuristic."""
    ticket = make_ticket(db_session, recall_number="D-REAL-2026-001", recall_number_is_fallback=False)
    evidence_service = FakeEvidenceService(chunks=[chunk()])
    llm_client = FakeLLMClient(
        answer="Grounded answer (source: sop.md, section: procedure)",
        fail_condense=True,
    )

    first = handle_chat(
        db=db_session,
        public_ticket_id=ticket.ticket_id,
        user_query="이 리콜에서 ICU 영향 있어?",
        session_id=None,
        retrieval_service=evidence_service,
        llm_client=llm_client,
    )
    second = handle_chat(
        db=db_session,
        public_ticket_id=ticket.ticket_id,
        user_query="그럼 격리는 어떻게 해?",
        session_id=first["session_id"],
        retrieval_service=evidence_service,
        llm_client=llm_client,
    )

    assert second["answer"] == "Grounded answer (source: sop.md, section: procedure)"
    assert "이 리콜에서 ICU 영향 있어?" in second["standalone_query"]


def test_handle_chat_answer_mode_ticket_state_only_skips_retrieval(db_session):
    ticket = make_ticket(
        db_session,
        sufficiency_check={
            "required_sources": ["policy", "sop"],
            "found_sources": ["policy"],
            "missing_sources": ["sop"],
            "weak_sources": [],
            "failure_reasons": [{"reason": "missing_required_document_type", "document_type": "sop"}],
            "coverage_score": 0.5,
            "evidence_status": "insufficient",
            "needs_evidence_review": True,
            "citations_ready": True,
        },
        policy_decision={
            "review_type": "evidence_review",
            "reasons": ["Required evidence is missing: sop."],
            "decision": "route_to_hitl",
        },
    )
    evidence_service = FakeEvidenceService(chunks=[chunk()])
    llm_client = FakeLLMClient(answer="Evidence is missing from the ticket state.")

    result = handle_chat(
        db=db_session,
        public_ticket_id=ticket.ticket_id,
        user_query="뭐가 부족해?",
        session_id=None,
        retrieval_service=evidence_service,
        llm_client=llm_client,
    )

    assert result["intent"] == "evidence_gap"
    assert result["answer_mode"] == "ticket_state_only"
    assert result["evidence_status"] == "insufficient"
    assert evidence_service.calls == []
    assert result["sources"] == []
    assert len(llm_client.completions.calls) == 1
    prompt = llm_client.completions.calls[0]["messages"][1]["content"]
    assert "missing_sources: sop" in prompt
    assert "failure_reasons:" in prompt
    assert "workflow_stage: PENDING_REVIEW" in prompt


def test_handle_chat_workflow_explanation_uses_hybrid_retrieval(db_session):
    ticket = make_ticket(
        db_session,
        policy_decision={
            "review_type": "evidence_review",
            "reasons": ["Required evidence is missing: sop."],
            "decision": "route_to_hitl",
        },
    )
    evidence_service = FakeEvidenceService(chunks=[chunk(document_type="policy", section="review_routing_rules")])
    llm_client = FakeLLMClient(answer="It was routed based on policy and ticket state.")

    result = handle_chat(
        db=db_session,
        public_ticket_id=ticket.ticket_id,
        user_query="왜 review로 갔어?",
        session_id=None,
        retrieval_service=evidence_service,
        llm_client=llm_client,
    )

    assert result["intent"] == "workflow_explanation"
    assert result["answer_mode"] == "hybrid"
    assert result["target_profile"] == "workflow_explanation"
    assert result["retrieved_evidence_scope"] == "workflow_routing_and_ticket_evidence"
    assert result["answer_support_level"] == "partial"
    assert "workflow routing review decision evidence sufficiency" in result["standalone_query"]
    assert len(evidence_service.calls) == 1
    assert evidence_service.calls[0]["query"] == result["standalone_query"]
    assert evidence_service.calls[0]["context"].target_profile == "workflow_explanation"
    assert result["sources"]
    prompt = llm_client.completions.calls[0]["messages"][1]["content"]
    assert "When ticket state status and retrieved evidence scope differ" in prompt


def test_workflow_explanation_profile_includes_ticket_specific_recall_notice_target():
    from app.rag.router import EvidenceRouter

    plan = EvidenceRouter().build_plan(
        RetrievalContext(
            event_type="recall",
            query="why final approval",
            target_profile="workflow_explanation",
        ),
        top_k=3,
    )

    target_pairs = [(target.document_type, target.sections, target.required) for target in plan.targets]
    assert ("recall_notice", ["recall_notice"], False) in target_pairs
    assert ("policy", ["evidence_requirements", "review_routing_rules"], True) in target_pairs
    assert ("sop", ["evidence_requirements", "review_routing"], True) in target_pairs


def test_build_ticket_state_summary_includes_routing_and_inventory_context(db_session):
    ticket = make_ticket(
        db_session,
        inventory_result={
            "matched": True,
            "match_type": "exact_ndc_match",
            "match_confidence": 0.97,
            "matched_rows": [
                {
                    "inventory_id": "INV-1",
                    "drug_name": "midazolam",
                    "ndc": "00641601441",
                    "lot": "LOT-A",
                    "quantity": 12,
                    "department": "ICU",
                    "days_remaining": 7,
                }
            ],
            "needs_identity_review": False,
        },
        impact_summary={
            "affected_departments": ["ICU"],
            "department_breakdown": {"ICU": 12},
            "total_quantity": 12,
            "priority": "HIGH",
            "urgent": True,
            "urgent_reason": "ICU inventory affected.",
        },
        sufficiency_check={
            "required_sources": ["recall_notice", "policy", "sop"],
            "found_sources": ["recall_notice", "policy"],
            "missing_sources": ["sop"],
            "weak_sources": [],
            "failure_reasons": [{"reason": "missing_required_document_type", "document_type": "sop"}],
            "coverage_score": 0.67,
            "evidence_status": "insufficient",
            "needs_evidence_review": True,
            "citations_ready": True,
        },
        policy_decision={
            "review_type": "evidence_review",
            "reasons": ["Required evidence is missing: sop."],
            "decision": "route_to_hitl",
        },
    )
    from app.orchestration.state import ticket_to_state

    summary = build_ticket_state_summary(ticket_to_state(db_session, ticket), workflow_stage=ticket.workflow_stage)

    assert "ticket_id: T-CHAT-001" in summary
    assert "workflow_stage: PENDING_REVIEW" in summary
    assert "inventory_impact: affected_departments=ICU" in summary
    assert "evidence_status: insufficient" in summary
    assert "coverage_score: 0.67" in summary
    assert "missing_sources: sop" in summary
    assert "policy_routing_reason: Required evidence is missing: sop." in summary


def test_get_session_messages_scoped_by_session_not_ticket(db_session):
    ticket = make_ticket(db_session)
    session_a = get_or_create_session(db_session, ticket.id, session_id=None)
    db_session.commit()

    from app.chat.handler import save_message, get_session_messages

    save_message(db_session, ticket.id, session_a.session_id, "user", "hello from session a")
    db_session.commit()

    session_b = get_or_create_session(db_session, ticket.id, session_id=None)
    # get_or_create_session reuses existing session when session_id is None,
    # so create a second session manually to test scoping.
    from app.db.models.chat_model import ChatSession
    import uuid
    session_b = ChatSession(
        session_id=str(uuid.uuid4()),
        ticket_id=ticket.id,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(session_b)
    db_session.flush()
    save_message(db_session, ticket.id, session_b.session_id, "user", "hello from session b")
    db_session.commit()

    messages_a = get_session_messages(db_session, session_a.session_id)
    messages_b = get_session_messages(db_session, session_b.session_id)

    assert len(messages_a) == 1
    assert messages_a[0].content == "hello from session a"
    assert len(messages_b) == 1
    assert messages_b[0].content == "hello from session b"


# ──────────────────────────────────────────────
# Session/message status (issue #109 item B)
# ──────────────────────────────────────────────

def test_new_session_defaults_to_active_status(db_session):
    ticket = make_ticket(db_session)

    session = get_or_create_session(db_session, ticket.id, session_id=None)
    db_session.commit()

    assert session.status == "active"


def test_successful_turn_saves_messages_with_succeeded_status(db_session):
    ticket = make_ticket(db_session)
    evidence_service = FakeEvidenceService(chunks=[chunk()])
    llm_client = FakeLLMClient()

    handle_chat(
        db=db_session,
        public_ticket_id=ticket.ticket_id,
        user_query="What does the SOP say?",
        session_id=None,
        retrieval_service=evidence_service,
        llm_client=llm_client,
    )

    messages = db_session.query(ChatMessage).filter(ChatMessage.ticket_id == ticket.id).all()
    assert len(messages) == 2
    assert all(message.status == "succeeded" for message in messages)


def test_retrieval_failure_persists_user_question_and_failed_assistant_message(db_session):
    """
    Regression test: a retrieval failure previously called db.rollback(),
    wiping out the just-created session and the user's just-saved question
    -- a failed turn left zero trace in the DB. Now the question and a
    failed-status assistant message must survive, and the client still gets
    an error response.
    """
    from fastapi import HTTPException

    ticket = make_ticket(db_session)
    evidence_service = FailingEvidenceService()
    llm_client = FakeLLMClient()

    with pytest.raises(HTTPException) as exc_info:
        handle_chat(
            db=db_session,
            public_ticket_id=ticket.ticket_id,
            user_query="What does the SOP say?",
            session_id=None,
            retrieval_service=evidence_service,
            llm_client=llm_client,
        )

    assert exc_info.value.status_code == 500

    session = db_session.query(ChatSession).filter(ChatSession.ticket_id == ticket.id).first()
    assert session is not None

    messages = (
        db_session.query(ChatMessage)
        .filter(ChatMessage.ticket_id == ticket.id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[0].content == "What does the SOP say?"
    assert messages[0].status == "succeeded"
    assert messages[1].role == "assistant"
    assert messages[1].status == "failed"


def test_llm_failure_persists_user_question_and_failed_assistant_message(db_session):
    """Same as the retrieval-failure regression test, but for the main
    chat-completion call failing after evidence was already retrieved."""
    from fastapi import HTTPException

    ticket = make_ticket(db_session)
    evidence_service = FakeEvidenceService(chunks=[chunk()])
    llm_client = FakeLLMClient(fail_answer=True)

    with pytest.raises(HTTPException) as exc_info:
        handle_chat(
            db=db_session,
            public_ticket_id=ticket.ticket_id,
            user_query="What does the SOP say?",
            session_id=None,
            retrieval_service=evidence_service,
            llm_client=llm_client,
        )

    assert exc_info.value.status_code == 500

    messages = (
        db_session.query(ChatMessage)
        .filter(ChatMessage.ticket_id == ticket.id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[0].status == "succeeded"
    assert messages[1].role == "assistant"
    assert messages[1].status == "failed"


def test_llm_client_initialization_failure_persists_user_question_and_failed_message(db_session):
    """
    Regression test: if build_llm_client() fails (e.g., missing API key,
    network error during client setup), the user question must still be
    persisted along with a failed assistant message, matching the same
    failure-handling pattern used for retrieval and completion errors.
    """
    from fastapi import HTTPException
    from unittest.mock import patch

    ticket = make_ticket(db_session)
    evidence_service = FakeEvidenceService(chunks=[chunk()])

    # Simulate build_llm_client() raising an exception (llm_client=None
    # triggers the real build_llm_client call inside handle_chat).
    with patch("app.chat.handler.build_llm_client") as mock_build:
        mock_build.side_effect = RuntimeError("API key missing or invalid")

        with pytest.raises(HTTPException) as exc_info:
            handle_chat(
                db=db_session,
                public_ticket_id=ticket.ticket_id,
                user_query="What does the SOP say?",
                session_id=None,
                retrieval_service=evidence_service,
                llm_client=None,  # Force call to build_llm_client
            )

    assert exc_info.value.status_code == 500

    session = db_session.query(ChatSession).filter(ChatSession.ticket_id == ticket.id).first()
    assert session is not None

    messages = (
        db_session.query(ChatMessage)
        .filter(ChatMessage.ticket_id == ticket.id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[0].content == "What does the SOP say?"
    assert messages[0].status == "succeeded"
    assert messages[1].role == "assistant"
    assert messages[1].content == "LLM client initialization failed for this question."
    assert messages[1].status == "failed"
