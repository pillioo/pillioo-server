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
    get_or_create_session,
    get_session_messages,
    handle_chat,
)
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
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(choices=[FakeChatChoice(self.answer)])


class FakeLLMClient:
    def __init__(self, answer: str = "Grounded answer (source: sop.md, section: procedure)") -> None:
        self.completions = FakeChatCompletions(answer)
        self.chat = SimpleNamespace(completions=self.completions)


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
        user_query="Anything at all?",
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


def test_get_session_messages_scoped_by_session_not_ticket(db_session):
    ticket = make_ticket(db_session)
    session_a = get_or_create_session(db_session, ticket.id, session_id=None)
    db_session.commit()

    from app.chat.handler import save_message

    save_message(db_session, ticket.id, session_a.session_id, "user", "hello from session a")
    db_session.commit()