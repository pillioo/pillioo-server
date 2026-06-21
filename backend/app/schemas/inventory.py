from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import Department, MatchType, Priority


class InventoryRow(BaseModel):
    inventory_id: str
    drug_name: str
    ndc: str
    lot: Optional[str] = None
    quantity: int = Field(..., ge=0)
    department: Department
    days_remaining: int = Field(..., ge=0)


class InventoryMatchResult(BaseModel):
    matched: bool
    match_type: MatchType
    match_confidence: float = Field(..., ge=0.0, le=1.0)
    matched_rows: list[InventoryRow] = Field(default_factory=list)
    needs_identity_review: bool = False
    identity_review_reason: Optional[str] = None

    @model_validator(mode="after")
    def check_consistency(self) -> "InventoryMatchResult":
        if not self.matched and self.matched_rows:
            raise ValueError("matched_rows must be empty when matched is false.")

        if self.matched and self.match_type == MatchType.NO_MATCH:
            raise ValueError("match_type cannot be no_match when matched is true.")
        
        if not self.matched and self.match_type != MatchType.NO_MATCH:
            raise ValueError("match_type must be no_match when matched is false.")

        if self.needs_identity_review and not self.identity_review_reason:
            raise ValueError(
                "identity_review_reason is required when needs_identity_review is true."
            )

        return self


class ImpactSummary(BaseModel):
    affected_departments: list[Department] = Field(default_factory=list)
    department_breakdown: dict[Department, int] = Field(default_factory=dict)
    total_quantity: int = Field(..., ge=0)
    priority: Priority
    urgent: bool = False
    urgent_reason: Optional[str] = None

    @model_validator(mode="after")
    def check_urgent_reason(self) -> "ImpactSummary":
        if self.urgent and not self.urgent_reason:
            raise ValueError("urgent_reason is required when urgent is true.")

        return self


class TrustCheckResult(BaseModel):
    confidence: float = Field(..., ge=0.0, le=1.0)
    flags: list[str] = Field(default_factory=list)
    review_required: bool = False