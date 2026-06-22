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
    coverage_score: float = Field(..., ge=0.0, le=1.0)
    evidence_status: EvidenceStatus
    needs_evidence_review: bool

    @model_validator(mode="after")
    def check_status_matches_missing(self) -> "SufficiencyCheckResult":
        has_missing = len(self.missing_sources) > 0

        if has_missing and self.evidence_status != EvidenceStatus.INSUFFICIENT:
            raise ValueError(
                "evidence_status must be insufficient when missing_sources is not empty."
            )

        if not has_missing and self.evidence_status != EvidenceStatus.SUFFICIENT:
            raise ValueError(
                "evidence_status must be sufficient when missing_sources is empty."
            )

        if has_missing != self.needs_evidence_review:
            raise ValueError(
                "needs_evidence_review must match whether missing_sources is non-empty."
            )

        return self