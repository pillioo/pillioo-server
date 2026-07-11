from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import DocumentType, EvidenceStatus


class EvidenceChunk(BaseModel):
    content: str
    document_type: DocumentType
    section: str
    similarity_score: float = Field(..., ge=0.0, le=1.0)
    source_path: str
    chunk_index: int = Field(..., ge=0)
    drug_name: Optional[str] = None
    filter_level: Optional[str] = None
    matched_identifiers: dict = Field(default_factory=dict)
    rank_reasons: list[str] = Field(default_factory=list)
    rank_score: Optional[float] = None


class Citation(BaseModel):
    source: str
    section: str
    score: float = Field(..., ge=0.0, le=1.0)


class DraftCitation(Citation):
    sentence: str


class EvidenceRoutingResult(BaseModel):
    target_document_types: list[DocumentType] = Field(..., min_length=1)
    target_sections: list[str] = Field(..., min_length=1)


class EvidenceResult(BaseModel):
    top_chunks: list[EvidenceChunk] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)


class SufficiencyCheckResult(BaseModel):
    required_sources: list[DocumentType]
    found_sources: list[DocumentType]
    missing_sources: list[DocumentType]
    # Sources that were found but only via a loose, non-section-specific match —
    # present, but not confidently relevant. Still counts as a gap for status purposes.
    weak_sources: list[DocumentType] = Field(default_factory=list)
    failure_reasons: list[dict] = Field(default_factory=list)
    coverage_score: float = Field(..., ge=0.0, le=1.0)
    evidence_status: EvidenceStatus
    needs_evidence_review: bool
    citations_ready: bool = True

    @model_validator(mode="after")
    def check_status_matches_missing(self) -> "SufficiencyCheckResult":
        has_gap = bool(self.missing_sources) or bool(self.weak_sources)
        has_non_source_failure = bool(self.failure_reasons) or not self.citations_ready

        if has_gap and self.evidence_status != EvidenceStatus.INSUFFICIENT:
            raise ValueError(
                "evidence_status must be insufficient when missing_sources or weak_sources is not empty."
            )

        if not has_gap and not has_non_source_failure and self.evidence_status != EvidenceStatus.SUFFICIENT:
            raise ValueError(
                "evidence_status must be sufficient when missing_sources and weak_sources are empty."
            )

        if has_non_source_failure and self.evidence_status != EvidenceStatus.INSUFFICIENT:
            raise ValueError(
                "evidence_status must be insufficient when citations are not ready or failure_reasons is not empty."
            )

        if has_non_source_failure and not self.needs_evidence_review:
            raise ValueError(
                "needs_evidence_review must be true when citations are not ready or failure_reasons is not empty."
            )

        if self.evidence_status == EvidenceStatus.INSUFFICIENT and not self.needs_evidence_review:
            raise ValueError(
                "needs_evidence_review must match whether missing_sources or weak_sources is non-empty."
            )

        if has_gap and not self.needs_evidence_review:
            raise ValueError(
                "needs_evidence_review must match whether missing_sources or weak_sources is non-empty."
            )

        if not has_gap and not has_non_source_failure and self.needs_evidence_review:
            raise ValueError(
                "needs_evidence_review must match whether missing_sources or weak_sources is non-empty."
            )

        return self
