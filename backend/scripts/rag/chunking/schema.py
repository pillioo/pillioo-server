from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


DocumentType = Literal["label", "recall_notice", "sop", "policy"]
EventType = Literal["recall", "shortage", "label_update"]


class EvidenceChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(..., min_length=1)
    document_id: str = Field(..., min_length=1)
    document_type: DocumentType
    event_type: EventType
    event_types: list[EventType] = Field(..., min_length=1)
    section: str = Field(..., min_length=1)
    section_title: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    chunk_index: int = Field(..., ge=0)
    token_count: int = Field(..., ge=1)
    content: str = Field(..., min_length=1)
    source_path: str = Field(..., min_length=1)

    drug_name: str | None = None
    normalized_drug_name: str | None = None
    rxnorm_rxcui: str | None = None
    classification: str | None = None
    ndc: list[str] | None = None
    lot: str | None = None
    recall_number: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
