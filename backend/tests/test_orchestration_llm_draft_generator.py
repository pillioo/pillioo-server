from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

from app.orchestration.draft import LLMDraftGenerator
from app.orchestration.service import DraftGenerator, SimpleDraftGenerator
from app.schemas.common import Classification, Department, EventType, Priority
from app.schemas.event import EventNormalized
from app.schemas.evidence import Citation, EvidenceChunk, EvidenceResult
from app.schemas.inventory import ImpactSummary
from app.schemas.workflow import TicketState


def event(**overrides) -> EventNormalized:
    defaults = dict(
        event_id="D-123-2026",
        event_type=EventType.RECALL,
        drug_name="midazolam",
        ndc="00641601441",
        lot="LOT-A",
        classification=Classification.CLASS_I,
        status="ongoing",
        recall_number="D-123-2026",
        reason_for_recall="Subpotent drug product",
        product_description="Midazolam HCl Injection 1 mg/mL vial",
    )
    defaults.update(overrides)
    return EventNormalized(**defaults)


def state(**overrides) -> TicketState:
    now = datetime.now(timezone.utc)
    defaults = dict(
        ticket_id="T-001",
        event_type=EventType.RECALL,
        classification=Classification.CLASS_I,
        event_normalized=event(),
        impact_summary=ImpactSummary(
            affected_departments=[Department.ICU],
            total_quantity=5,
            priority=Priority.HIGH,
        ),
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    return TicketState(**defaults)


def chunk(**overrides) -> EvidenceChunk:
    defaults = dict(
        content="Quarantine affected lots pending pharmacist review per SOP section 4.2.",
        document_type="sop",
        section="quarantine_procedure",
        similarity_score=0.9,
        source_path="recall_sop.md",
        chunk_index=0,
        drug_name="midazolam",
    )
    defaults.update(overrides)
    return EvidenceChunk(**defaults)


class FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = FakeMessage(content)


class FakeCompletions:
    def __init__(self, response_json: dict) -> None:
        self.response_json = response_json
        self.calls: list[dict] = []

    def create(self, **kwargs) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(choices=[FakeChoice(json.dumps(self.response_json))])


class FakeOpenAIClient:
    """Stub matching the subset of the OpenAI client surface LLMDraftGenerator uses."""

    def __init__(self, response_json: dict) -> None:
        self.completions = FakeCompletions(response_json)
        self.chat = SimpleNamespace(completions=self.completions)


def test_llm_draft_generator_satisfies_draft_generator_protocol() -> None:
    generator: DraftGenerator = LLMDraftGenerator(
        model="test-model",
        client=FakeOpenAIClient({"draft_text": "x", "citations": []}),
    )
    assert hasattr(generator, "generate")
    result = generator.generate(state=state(), evidence_result=EvidenceResult(top_chunks=[], citations=[]))
    draft_text, citations = result
    assert isinstance(draft_text, str)
    assert isinstance(citations, list)


def test_llm_draft_generator_resolves_citations_against_real_evidence_scores() -> None:
    evidence = EvidenceResult(
        top_chunks=[chunk()],
        citations=[Citation(source="recall_sop.md", section="quarantine_procedure", score=0.9)],
    )
    fake_client = FakeOpenAIClient(
        {
            "draft_text": "Midazolam lots are recalled. Quarantine affected lots pending pharmacist review.",
            "citations": [
                {
                    "source": "recall_sop.md",
                    "section": "quarantine_procedure",
                    "sentence": "Quarantine affected lots pending pharmacist review.",
                }
            ],
        }
    )
    generator = LLMDraftGenerator(model="test-model", client=fake_client)

    draft_text, citations = generator.generate(state=state(), evidence_result=evidence)

    assert draft_text == "Midazolam lots are recalled. Quarantine affected lots pending pharmacist review."
    assert len(citations) == 1
    assert citations[0].source == "recall_sop.md"
    assert citations[0].section == "quarantine_procedure"
    # score must come from the real evidence citation, never from the model's own output.
    assert citations[0].score == 0.9
    assert citations[0].sentence == "Quarantine affected lots pending pharmacist review."

    call = fake_client.completions.calls[0]
    assert call["model"] == "test-model"
    assert "recall_sop.md" in call["messages"][1]["content"]
    assert "midazolam" in call["messages"][1]["content"]


def test_llm_draft_generator_drops_hallucinated_citation_and_falls_back_to_real_evidence() -> None:
    evidence = EvidenceResult(
        top_chunks=[chunk()],
        citations=[Citation(source="recall_sop.md", section="quarantine_procedure", score=0.9)],
    )
    fake_client = FakeOpenAIClient(
        {
            "draft_text": "Please review the affected midazolam lots.",
            "citations": [{"source": "made_up_policy.md", "section": "nonexistent", "sentence": "fabricated"}],
        }
    )
    generator = LLMDraftGenerator(model="test-model", client=fake_client)

    draft_text, citations = generator.generate(state=state(), evidence_result=evidence)

    assert draft_text == "Please review the affected midazolam lots."
    assert all(citation.source != "made_up_policy.md" for citation in citations)
    # Evidence exists, so draft_citations must not come back empty.
    assert len(citations) == 1
    assert citations[0].source == "recall_sop.md"
    assert citations[0].score == 0.9


def test_llm_draft_generator_returns_empty_citations_without_crashing_when_no_evidence() -> None:
    evidence = EvidenceResult(top_chunks=[], citations=[])
    fake_client = FakeOpenAIClient({"draft_text": "should not be used", "citations": []})
    generator = LLMDraftGenerator(model="test-model", client=fake_client)

    draft_text, citations = generator.generate(state=state(), evidence_result=evidence)

    assert citations == []
    assert isinstance(draft_text, str)
    assert draft_text
    # Nothing to ground a draft on -> the model must not even be called.
    assert fake_client.completions.calls == []


def test_simple_draft_generator_remains_available_as_deterministic_test_fallback() -> None:
    draft_text, citations = SimpleDraftGenerator().generate(
        state=state(), evidence_result=EvidenceResult(top_chunks=[], citations=[])
    )
    assert isinstance(draft_text, str) and draft_text
    assert citations == []
