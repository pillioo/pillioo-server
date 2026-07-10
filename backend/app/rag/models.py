from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RetrievalContext:
    event_type: str | None = None
    query: str = ""
    drug_name: str | None = None
    normalized_drug_name: str | None = None
    rxnorm_rxcui: str | None = None
    ndc: list[str] = field(default_factory=list)
    lot: str | None = None
    recall_number: str | None = None
    classification: str | None = None


@dataclass(frozen=True)
class EvidenceTarget:
    document_type: str
    required: bool = True
    sections: list[str] = field(default_factory=list)
    top_k: int = 5

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_type": self.document_type,
            "required": self.required,
            "sections": self.sections,
            "top_k": self.top_k,
        }


@dataclass(frozen=True)
class EvidencePlan:
    event_type: str | None
    targets: list[EvidenceTarget]

    @property
    def required_document_types(self) -> list[str]:
        return [target.document_type for target in self.targets if target.required]


@dataclass
class EvidenceChunk:
    chunk_id: str
    chunk_index: int
    content: str
    document_id: str
    document_type: str
    event_type: str
    section: str
    source_path: str
    score: float
    title: str | None = None
    section_title: str | None = None
    drug_name: str | None = None
    normalized_drug_name: str | None = None
    rxnorm_rxcui: str | None = None
    classification: str | None = None
    ndc: list[str] = field(default_factory=list)
    lot: str | None = None
    recall_number: str | None = None
    content_hash: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    filter_expr: str = ""
    filter_level: str = ""
    target_document_type: str | None = None
    rank_score: float = 0.0
    rank_reasons: list[str] = field(default_factory=list)
    matched_identifiers: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_hit(
        cls,
        hit: dict[str, Any],
        *,
        filter_expr: str = "",
        filter_level: str = "",
        target_document_type: str | None = None,
    ) -> "EvidenceChunk":
        return cls(
            chunk_id=str(hit.get("chunk_id") or ""),
            chunk_index=int(hit.get("chunk_index") or 0),
            content=str(hit.get("content") or ""),
            document_id=str(hit.get("document_id") or ""),
            document_type=str(hit.get("document_type") or ""),
            event_type=str(hit.get("event_type") or ""),
            section=str(hit.get("section") or ""),
            source_path=str(hit.get("source_path") or ""),
            score=float(hit.get("score") or 0.0),
            title=hit.get("title"),
            section_title=hit.get("section_title"),
            drug_name=hit.get("drug_name"),
            normalized_drug_name=hit.get("normalized_drug_name"),
            rxnorm_rxcui=hit.get("rxnorm_rxcui"),
            classification=hit.get("classification"),
            ndc=list_values(hit.get("ndc")),
            lot=hit.get("lot"),
            recall_number=hit.get("recall_number"),
            content_hash=hit.get("content_hash"),
            # "metadata" fallback lets tests/fakes skip the Milvus "metadata_json" key.
            metadata=hit.get("metadata_json") or hit.get("metadata") or {},
            filter_expr=filter_expr,
            filter_level=filter_level,
            target_document_type=target_document_type,
            rank_score=float(hit.get("score") or 0.0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "rank_score": self.rank_score,
            "rank_reasons": self.rank_reasons,
            "matched_identifiers": self.matched_identifiers,
            "chunk_id": self.chunk_id,
            "chunk_index": self.chunk_index,
            "content": self.content,
            "document_id": self.document_id,
            "document_type": self.document_type,
            "event_type": self.event_type,
            "section": self.section,
            "title": self.title,
            "section_title": self.section_title,
            "source_path": self.source_path,
            "drug_name": self.drug_name,
            "normalized_drug_name": self.normalized_drug_name,
            "rxnorm_rxcui": self.rxnorm_rxcui,
            "classification": self.classification,
            "ndc": self.ndc,
            "lot": self.lot,
            "recall_number": self.recall_number,
            "content_hash": self.content_hash,
            "metadata_json": self.metadata,
            "filter_expr": self.filter_expr,
            "filter_level": self.filter_level,
            "target_document_type": self.target_document_type,
        }


@dataclass(frozen=True)
class SufficiencyResult:
    required_document_types: list[str]
    found_document_types: list[str]
    missing_document_types: list[str]
    # Required types whose only evidence came from the loosest (document_type-only)
    # filter fallback — none of the sections we actually care about were matched.
    weak_document_types: list[str]
    coverage_score: float
    evidence_status: str
    needs_evidence_review: bool
    citations_ready: bool
    failure_reasons: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class EvidenceResult:
    query: str
    context: RetrievalContext
    plan: EvidencePlan
    chunks: list[EvidenceChunk]
    sufficiency: SufficiencyResult
    retrieval_trace: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "context": self.context,
            "required_document_types": self.sufficiency.required_document_types,
            "found_document_types": self.sufficiency.found_document_types,
            "missing_document_types": self.sufficiency.missing_document_types,
            "weak_document_types": self.sufficiency.weak_document_types,
            "failure_reasons": self.sufficiency.failure_reasons,
            "coverage_score": self.sufficiency.coverage_score,
            "evidence_status": self.sufficiency.evidence_status,
            "needs_evidence_review": self.sufficiency.needs_evidence_review,
            "citations_ready": self.sufficiency.citations_ready,
            "retrieval_trace": self.retrieval_trace,
            "chunks": [chunk.to_dict() for chunk in self.chunks],
        }


def list_values(value: Any) -> list[str]:
    if value is None:
        return []
    # pymilvus search() returns ARRAY fields as a protobuf RepeatedScalarContainer,
    # not a list, so isinstance(value, list) alone misses it.
    if isinstance(value, (str, bytes)):
        values = [value]
    elif isinstance(value, Iterable):
        values = list(value)
    else:
        values = [value]
    return [str(item) for item in values if item is not None and str(item).strip()]
