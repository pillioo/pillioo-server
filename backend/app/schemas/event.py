from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.common import BlockedCategory, Classification, EventType


class EventNormalized(BaseModel):
    """Normalized FDA event used to initialize a ticket."""

    model_config = ConfigDict(frozen=True)

    event_id: str = Field(..., description="Source FDA event identifier.")
    event_type: EventType
    drug_name: str = Field(..., min_length=1, description="Normalized generic drug name.")
    ndc: str = Field(..., description="Standard 11-digit NDC.")
    lot: Optional[str] = None
    classification: Optional[Classification] = None
    status: str = Field(..., description="Source FDA status, such as ongoing or terminated.")
    recall_initiation_date: Optional[date] = None

    # recall_number is the FDA-domain identifier used for recall notice lookup.
    # If the source does not provide it, event_id is used explicitly and tracked.
    recall_number: str = Field(description="Raw FDA recall number used for FDA recall lookup.")
    recall_number_is_fallback: bool = False
    product_description: Optional[str] = Field(
        None,
        description=(
            "Source-provided FDA product text. drug_name may be used downstream as a "
            "separate fallback query term, but this field is not inferred from it."
        ),
    )
    reason_for_recall: Optional[str] = Field(None, description="FDA-provided reason for recall.")

    @model_validator(mode="before")
    @classmethod
    def fill_fda_handoff_fields(cls, data):
        if not isinstance(data, dict):
            return data

        values = dict(data)
        if values.get("recall_number") is None:
            values["recall_number"] = values.get("event_id")
            values["recall_number_is_fallback"] = True
        else:
            values.setdefault("recall_number_is_fallback", False)
        return values

    @field_validator("ndc")
    @classmethod
    def validate_ndc_format(cls, value: str) -> str:
        if not (value.isdigit() and len(value) == 11):
            raise ValueError(f"NDC must be an 11-digit number. Received: {value!r}")
        return value

    @field_validator("drug_name")
    @classmethod
    def normalize_drug_name(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("drug_name must not be empty.")
        return normalized

    @model_validator(mode="after")
    def check_recall_fields(self) -> "EventNormalized":
        if self.event_type == EventType.RECALL and self.classification is None:
            raise ValueError("classification is required when event_type is recall.")
        return self


class BlockedSentence(BaseModel):
    original: str
    category: BlockedCategory
    replaced_with: str


class SafetyCheckResult(BaseModel):
    blocked_sentences: list[BlockedSentence] = Field(default_factory=list)
    revised_draft: str
    needs_action_review: bool = False

    @model_validator(mode="after")
    def check_consistency(self) -> "SafetyCheckResult":
        if self.blocked_sentences and not self.needs_action_review:
            raise ValueError(
                "needs_action_review must be true when blocked_sentences is not empty."
            )

        if not self.blocked_sentences and self.needs_action_review:
            raise ValueError(
                "needs_action_review must be false when blocked_sentences is empty."
            )

        return self
