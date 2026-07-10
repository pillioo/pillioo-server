from __future__ import annotations

from app.rag.adapter import (
    to_citation,
    to_evidence_result,
    to_schema_chunk,
    to_sufficiency_check_result,
    to_ticket_state_fields,
)
from app.rag.models import EvidenceChunk, EvidenceResult, EvidencePlan, RetrievalContext, SufficiencyResult


def chunk(**overrides: object) -> EvidenceChunk:
    defaults = {
        "chunk_id": "recall-d_0277_2024::recall_notice::0002",
        "chunk_index": 2,
        "content": "body",
        "document_id": "recall-d_0277_2024",
        "document_type": "recall_notice",
        "event_type": "recall",
        "section": "recall_notice",
        "source_path": "data/rag/documents/recall_notice/recall-d_0277_2024.md",
        "score": 0.82,
        "drug_name": "fentanyl",
    }
    defaults.update(overrides)
    return EvidenceChunk(**defaults)


def sufficiency(**overrides: object) -> SufficiencyResult:
    defaults = {
        "required_document_types": ["recall_notice", "policy"],
        "found_document_types": ["recall_notice", "policy"],
        "missing_document_types": [],
        "weak_document_types": [],
        "coverage_score": 1.0,
        "evidence_status": "sufficient",
        "needs_evidence_review": False,
        "citations_ready": True,
    }
    defaults.update(overrides)
    return SufficiencyResult(**defaults)


def test_to_schema_chunk_maps_chunk_index_and_identity_fields() -> None:
    schema_chunk = to_schema_chunk(chunk())

    assert schema_chunk.chunk_index == 2
    assert schema_chunk.document_type == "recall_notice"
    assert schema_chunk.drug_name == "fentanyl"


def test_to_schema_chunk_and_citation_clamp_negative_score() -> None:
    schema_chunk = to_schema_chunk(chunk(score=-0.2))
    citation = to_citation(chunk(score=-0.2))

    assert schema_chunk.similarity_score == 0.0
    assert citation.score == 0.0


def test_to_schema_chunk_and_citation_clamp_score_above_one() -> None:
    schema_chunk = to_schema_chunk(chunk(score=1.4))
    citation = to_citation(chunk(score=1.4))

    assert schema_chunk.similarity_score == 1.0
    assert citation.score == 1.0


def test_to_evidence_result_maps_chunks_to_top_chunks_and_citations() -> None:
    result = EvidenceResult(
        query="q",
        context=RetrievalContext(),
        plan=EvidencePlan(event_type="recall", targets=[]),
        chunks=[chunk(), chunk(chunk_id="recall-d_0277_2024::recall_notice::0003", chunk_index=3)],
        sufficiency=sufficiency(),
    )

    schema_result = to_evidence_result(result)

    assert len(schema_result.top_chunks) == 2
    assert len(schema_result.citations) == 2
    assert schema_result.citations[0].source == chunk().source_path


def test_to_sufficiency_check_result_keeps_weak_sources_separate_from_missing() -> None:
    result = to_sufficiency_check_result(
        sufficiency(
            missing_document_types=[],
            weak_document_types=["policy"],
            evidence_status="insufficient",
            needs_evidence_review=True,
        )
    )

    assert result.missing_sources == []
    assert result.weak_sources == ["policy"]
    assert result.evidence_status == "insufficient"
    assert result.needs_evidence_review is True


def test_to_sufficiency_check_result_maps_failure_reasons() -> None:
    result = to_sufficiency_check_result(
        sufficiency(
            evidence_status="insufficient",
            needs_evidence_review=True,
            citations_ready=False,
            failure_reasons=[{"reason": "citation_not_ready"}],
        )
    )

    assert result.failure_reasons == [{"reason": "citation_not_ready"}]
    assert result.citations_ready is False
    assert result.evidence_status == "insufficient"


def test_to_ticket_state_fields_returns_matching_pair() -> None:
    result = EvidenceResult(
        query="q",
        context=RetrievalContext(),
        plan=EvidencePlan(event_type="recall", targets=[]),
        chunks=[chunk()],
        sufficiency=sufficiency(),
    )

    evidence_result, sufficiency_check = to_ticket_state_fields(result)

    assert len(evidence_result.top_chunks) == 1
    assert sufficiency_check.evidence_status == "sufficient"
