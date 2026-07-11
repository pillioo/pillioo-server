from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


# JSONB has no sqlite compiler by default; map it to plain JSON so the real
# ORM models/tables can be created against an in-memory sqlite DB for this
# end-to-end test instead of requiring a live Postgres instance.
@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json_for_sqlite(element, compiler, **kw):
    return "JSON"


from app.db.base import Base
from app.db.session import get_db
import app.db.models.approval_model  # noqa: F401
import app.db.models.audit_log_model  # noqa: F401
import app.db.models.chat_model  # noqa: F401
import app.db.models.report_version_model  # noqa: F401
import app.db.models.ticket  # noqa: F401

import app.chat.router as chat_router_module
import app.orchestration.router as orchestration_router_module
import app.orchestration.draft as orchestration_draft_module
from app.main import app
from app.rag.models import (
    EvidenceChunk as RagEvidenceChunk,
    EvidencePlan,
    EvidenceResult as RagEvidenceResult,
    EvidenceTarget,
    RetrievalContext,
    SufficiencyResult,
)


class FakeEvidenceService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def retrieve(self, *, query, context=None, top_k=5, filter_override=None):
        self.calls.append({"query": query, "context": context, "top_k": top_k})
        plan = EvidencePlan(
            event_type="recall",
            targets=[EvidenceTarget("recall_notice"), EvidenceTarget("policy"), EvidenceTarget("sop")],
        )
        chunks = [
            RagEvidenceChunk(
                chunk_id="chunk-1", chunk_index=0,
                content="Quarantine affected lots pending pharmacist review per SOP section 4.2.",
                document_id="doc-1", document_type="recall_notice", event_type="recall",
                section="recall_notice", source_path="recall.md", score=0.91,
                drug_name="midazolam", normalized_drug_name="midazolam", recall_number="D-TEST-2026-001",
            ),
            RagEvidenceChunk(
                chunk_id="chunk-2", chunk_index=0,
                content="Policy requires quarantine and pharmacist sign-off before disposition.",
                document_id="doc-2", document_type="policy", event_type="recall",
                section="required_actions", source_path="policy.md", score=0.88,
                drug_name="midazolam", normalized_drug_name="midazolam",
            ),
            RagEvidenceChunk(
                chunk_id="chunk-3", chunk_index=0,
                content="SOP: hold recalled lots in quarantine area B pending pharmacist review.",
                document_id="doc-3", document_type="sop", event_type="recall",
                section="procedure", source_path="sop.md", score=0.87,
                drug_name="midazolam", normalized_drug_name="midazolam",
            ),
        ]
        sufficiency = SufficiencyResult(
            required_document_types=["recall_notice", "policy", "sop"],
            found_document_types=["recall_notice", "policy", "sop"],
            missing_document_types=[],
            weak_document_types=[],
            coverage_score=1.0,
            evidence_status="sufficient",
            needs_evidence_review=False,
            citations_ready=True,
        )
        return RagEvidenceResult(
            query=query,
            context=context or RetrievalContext(),
            plan=plan,
            chunks=chunks,
            sufficiency=sufficiency,
        )


class FakeChatCompletionMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class FakeChatChoice:
    def __init__(self, content: str) -> None:
        self.message = FakeChatCompletionMessage(content)


class FakeChatCompletions:
    def __init__(self, response_provider) -> None:
        self.response_provider = response_provider
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(choices=[FakeChatChoice(self.response_provider(kwargs))])


class FakeOpenAIClient:
    """Stands in both for the draft generator's LLM client and the chat LLM client."""

    def __init__(self, response_provider) -> None:
        self.chat = SimpleNamespace(completions=FakeChatCompletions(response_provider))


def _draft_response_provider(kwargs: dict) -> str:
    return json.dumps(
        {
            "title": "Midazolam class I recall review draft",
            "summary": (
                "Midazolam class I recall notice. Quarantine affected lots pending "
                "pharmacist review per SOP section 4.2."
            ),
            "recommended_review_action": "Pharmacist review required before further action.",
            "citations": [
                {
                    "source": "sop.md",
                    "section": "procedure",
                    "sentence": "Quarantine affected lots pending pharmacist review per SOP section 4.2.",
                }
            ],
        }
    )


def _chat_response_provider(kwargs: dict) -> str:
    return (
        "This ticket was routed to review because evidence coverage was sufficient and a "
        "draft has already been generated. (source: sop.md, section: procedure)"
    )


@pytest.fixture()
def client(monkeypatch):
    # StaticPool is required for an in-memory sqlite DB: without it, each
    # checked-out connection is a brand new (and therefore empty) database.
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    fake_evidence_service = FakeEvidenceService()

    # /tickets/{id}/run builds RetrievalService.from_milvus(...) directly (no DI
    # hook), so patch the classmethod itself to avoid a real Milvus/OpenAI call.
    monkeypatch.setattr(
        orchestration_router_module.RetrievalService,
        "from_milvus",
        classmethod(lambda cls, **kwargs: fake_evidence_service),
    )
    # LLMDraftGenerator() is constructed with no args as run_ticket_workflow's
    # default; patch OpenAI at its import site so it never touches the network.
    monkeypatch.setattr(
        orchestration_draft_module,
        "OpenAI",
        lambda **kwargs: FakeOpenAIClient(_draft_response_provider),
    )

    app.dependency_overrides[chat_router_module.get_retrieval_service] = lambda: fake_evidence_service
    app.dependency_overrides[chat_router_module.get_llm_client] = lambda: FakeOpenAIClient(_chat_response_provider)

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def _upload_and_run(client: TestClient, recall_number: str = "D-TEST-2026-001") -> str:
    # recall_number doubles as the event_id for in-process dedup (app.event.dedup
    # keeps an in-memory set for the life of the test process), so each test
    # must use its own unique recall_number to avoid a false-positive 409.
    payload = {
        "recall_number": recall_number,
        "product_description": "Midazolam HCl Injection 1 mg/mL vial",
        "reason_for_recall": "Subpotent drug product",
        "classification": "class_i",
        "product_ndc": "00641-6014-41",
        "lot_number": "LOT-A",
        "recall_initiation_date": "2026-07-09",
        "status": "ongoing",
    }
    upload_resp = client.post("/events/upload", json=payload)
    assert upload_resp.status_code == 200, upload_resp.text
    ticket_id = upload_resp.json()["ticket_id"]
    assert ticket_id

    run_resp = client.post(f"/tickets/{ticket_id}/run")
    assert run_resp.status_code == 200, run_resp.text

    return ticket_id


def test_upload_run_draft_is_llm_generated_not_template(client: TestClient) -> None:
    ticket_id = _upload_and_run(client, recall_number="D-TEST-2026-001")

    detail_resp = client.get(f"/tickets/{ticket_id}")
    assert detail_resp.status_code == 200, detail_resp.text

    review_resp = client.get(f"/tickets/{ticket_id}/review")
    assert review_resp.status_code == 200, review_resp.text
    payload = review_resp.json()
    template_sentence = (
        "midazolam class_i recall notice. Affected departments: no affected departments. "
        "Hold affected inventory for pharmacist review before further action."
    )
    # The SimpleDraftGenerator template always produces this exact text; the
    # real draft (from our fake LLM response) must not match it.
    assert payload["draft_text"] != template_sentence
    assert "Quarantine affected lots pending pharmacist review per SOP section 4.2." in payload["draft_text"]


def test_chat_multi_turn_reuses_same_session_and_history_is_scoped(client: TestClient) -> None:
    ticket_id = _upload_and_run(client, recall_number="D-TEST-2026-002")

    first = client.post(f"/chat/{ticket_id}", json={"user_query": "What evidence supports quarantine?"})
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["session_id"]
    assert first_body["sources"]
    assert "sop.md" in first_body["answer"]

    second = client.post(f"/chat/{ticket_id}", json={"user_query": "Why was this routed for review?"})
    assert second.status_code == 200, second.text
    second_body = second.json()

    # Bug fix under test: with no session_id given, the ticket's existing
    # session must be reused, not silently recreated.
    assert second_body["session_id"] == first_body["session_id"]

    history_resp = client.get(f"/chat/{ticket_id}/history")
    assert history_resp.status_code == 200, history_resp.text
    history = history_resp.json()
    assert len(history) == 4
    session_ids = set()
    for message in history:
        session_ids.add(message["session_id"])
    assert session_ids == {first_body["session_id"]}
    roles = [message["role"] for message in history]
    assert roles == ["user", "assistant", "user", "assistant"]


def test_chat_explicit_session_id_still_works(client: TestClient) -> None:
    ticket_id = _upload_and_run(client, recall_number="D-TEST-2026-003")

    first = client.post(f"/chat/{ticket_id}", json={"user_query": "First question"})
    session_id = first.json()["session_id"]

    second = client.post(
        f"/chat/{ticket_id}", json={"user_query": "Second question", "session_id": session_id}
    )
    assert second.status_code == 200, second.text
    assert second.json()["session_id"] == session_id


def test_upload_run_approve_freezes_structured_final_v1(client: TestClient) -> None:
    """Full chain: upload -> run (draft_v1 as a structured DraftReport) ->
    approve (final_v1 frozen from draft_v1, no LLM regeneration). Closes the
    gap where draft_v1 generation and the approval/versioning flow were only
    ever tested separately, never chained end-to-end."""
    ticket_id = _upload_and_run(client, recall_number="D-TEST-2026-004")

    versions_resp = client.get(f"/reports/{ticket_id}/versions")
    assert versions_resp.status_code == 200, versions_resp.text
    versions = versions_resp.json()
    assert len(versions) == 1
    draft_v1 = versions[0]
    assert draft_v1["version_tag"] == "draft_v1"
    assert draft_v1["report"] is not None
    assert draft_v1["report"]["title"] == "Midazolam class I recall review draft"
    assert draft_v1["report"]["affected_product"]["drug_name"] == "midazolam"
    assert draft_v1["created_by"] == "workflow"

    approve_resp = client.post(
        f"/approval/{ticket_id}/approve",
        json={"reviewer": "pharm-1", "comment": "Looks good."},
    )
    assert approve_resp.status_code == 200, approve_resp.text
    approve_body = approve_resp.json()
    assert approve_body["approval_status"] == "approved"
    assert approve_body["final_report_version"] == "final_v1"

    versions_after = client.get(f"/reports/{ticket_id}/versions").json()
    assert len(versions_after) == 2
    final_v1 = next(v for v in versions_after if v["version_tag"] == "final_v1")

    # final_v1 must be a byte-for-byte freeze of draft_v1 -- same structured
    # report and same flattened text, no LLM regeneration involved.
    assert final_v1["report"] == draft_v1["report"]
    assert final_v1["report_text"] == draft_v1["report_text"]
    assert final_v1["source_version"] == "draft_v1"
    assert final_v1["approved_by"] == "pharm-1"
    assert final_v1["approval_comment"] == "Looks good."
    assert final_v1["approved_at"] is not None


def test_revise_with_llm_rejected_after_ticket_approved(client: TestClient) -> None:
    """Once a ticket is approved (final_v1 frozen), /revise-with-llm must be
    rejected instead of silently appending another draft_v2 behind the
    pharmacist's back."""
    ticket_id = _upload_and_run(client, recall_number="D-TEST-2026-005")

    approve_resp = client.post(
        f"/approval/{ticket_id}/approve",
        json={"reviewer": "pharm-1", "comment": "Looks good."},
    )
    assert approve_resp.status_code == 200, approve_resp.text

    revise_resp = client.post(
        f"/approval/{ticket_id}/revise-with-llm",
        json={"reviewer": "pharm-1", "reviewer_comment": "please soften the tone"},
    )
    assert revise_resp.status_code == 422, revise_resp.text
    body = revise_resp.json()["detail"]
    assert body["error_code"] == "INVALID_VERSION_TAG"

    # No extra draft_v2 must have been created by the rejected request.
    versions_after = client.get(f"/reports/{ticket_id}/versions").json()
    assert [v["version_tag"] for v in versions_after] == ["draft_v1", "final_v1"]
