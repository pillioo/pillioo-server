from __future__ import annotations

from app.rag.models import EvidenceChunk as RagEvidenceChunk
from app.rag.models import EvidenceResult as RagEvidenceResult
from app.rag.models import SufficiencyResult as RagSufficiencyResult
from app.schemas.evidence import Citation, EvidenceChunk, EvidenceResult, SufficiencyCheckResult


def _clamp_score(score: float) -> float:
    return max(0.0, min(1.0, score))


def to_schema_chunk(chunk: RagEvidenceChunk) -> EvidenceChunk:
    return EvidenceChunk(
        content=chunk.content,
        document_type=chunk.document_type,
        section=chunk.section,
        similarity_score=_clamp_score(chunk.score),
        source_path=chunk.source_path,
        chunk_index=chunk.chunk_index,
        drug_name=chunk.drug_name,
        filter_level=chunk.filter_level,
        matched_identifiers=chunk.matched_identifiers,
        rank_reasons=chunk.rank_reasons,
        rank_score=chunk.rank_score,
        lexical_overlap_score=chunk.lexical_overlap_score,
        lexical_overlap_terms=chunk.lexical_overlap_terms,
    )


def to_citation(chunk: RagEvidenceChunk) -> Citation:
    return Citation(
        source=chunk.source_path,
        section=chunk.section,
        score=_clamp_score(chunk.score),
    )


def to_evidence_result(result: RagEvidenceResult) -> EvidenceResult:
    return EvidenceResult(
        top_chunks=[to_schema_chunk(chunk) for chunk in result.chunks],
        citations=[to_citation(chunk) for chunk in result.chunks],
    )


def to_sufficiency_check_result(sufficiency: RagSufficiencyResult) -> SufficiencyCheckResult:
    return SufficiencyCheckResult(
        required_sources=sufficiency.required_document_types,
        found_sources=sufficiency.found_document_types,
        missing_sources=sufficiency.missing_document_types,
        weak_sources=sufficiency.weak_document_types,
        failure_reasons=sufficiency.failure_reasons,
        coverage_score=sufficiency.coverage_score,
        evidence_status=sufficiency.evidence_status,
        needs_evidence_review=sufficiency.needs_evidence_review,
        citations_ready=sufficiency.citations_ready,
    )


def to_ticket_state_fields(result: RagEvidenceResult) -> tuple[EvidenceResult, SufficiencyCheckResult]:
    return to_evidence_result(result), to_sufficiency_check_result(result.sufficiency)
