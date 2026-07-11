from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import (
    ApprovalStatus,
    Classification,
    EventType,
    PolicyDecisionAction,
    Priority,
    ReviewType,
    TicketStatus,
    WorkflowStep,
)
from app.schemas.event import EventNormalized, SafetyCheckResult
from app.schemas.evidence import DraftCitation, EvidenceResult, SufficiencyCheckResult
from app.schemas.inventory import ImpactSummary, InventoryMatchResult, TrustCheckResult
from app.schemas.report import DraftReport


class TrustChecks(BaseModel):
    inventory: Optional[TrustCheckResult] = None
    rag: Optional[TrustCheckResult] = None


class ReviewDecision(BaseModel):
    review_type: ReviewType
    reasons: list[str] = Field(default_factory=list)
    decision: PolicyDecisionAction

    @staticmethod
    def expected_action(review_type: ReviewType) -> PolicyDecisionAction:
        if review_type == ReviewType.NO_IMPACT_CLOSE:
            return PolicyDecisionAction.CLOSE

        if review_type == ReviewType.FINAL_APPROVAL:
            return PolicyDecisionAction.REQUEST_FINAL_APPROVAL

        return PolicyDecisionAction.ROUTE_TO_HITL

    @model_validator(mode="after")
    def check_decision_matches_review_type(self) -> "ReviewDecision":
        expected = self.expected_action(self.review_type)

        if self.decision != expected:
            raise ValueError(
                f"decision must be {expected.value!r} when review_type is "
                f"{self.review_type.value!r}."
            )

        return self


class AuditLogEntry(BaseModel):
    ticket_id: str
    step_name: WorkflowStep
    input_json: dict[str, Any]
    output_json: dict[str, Any]
    timestamp: datetime
    duration_ms: int = Field(..., ge=0)

    # Display-friendly fields for a frontend timeline, derived from
    # step_name/output_json (see app.audit.logger.derive_display_fields).
    # Additive/backward-compatible -- input_json/output_json are unchanged.
    title: str
    message: str
    severity: str  # "info" | "warning" | "error"
    status: str  # "succeeded" | "failed" | "skipped"


class TicketState(BaseModel):
    """Accumulated workflow state for a single ticket."""

    model_config = ConfigDict(validate_assignment=True)

    ticket_id: str
    event_type: EventType
    classification: Optional[Classification] = None
    status: TicketStatus = TicketStatus.CREATED

    event_normalized: Optional[EventNormalized] = None
    inventory_result: Optional[InventoryMatchResult] = None
    impact_summary: Optional[ImpactSummary] = None
    evidence_result: Optional[EvidenceResult] = None
    sufficiency_check: Optional[SufficiencyCheckResult] = None

    # Structured draft_v1/draft_v2 content (see app.schemas.report.DraftReport).
    # Only populated in-memory during a workflow run that generated a fresh
    # draft; reconstructing TicketState from a persisted Ticket row (e.g. in
    # app.orchestration.state.ticket_to_state) leaves this as None since the
    # structured body lives on the ReportVersion row, not on Ticket itself.
    draft_report: Optional[DraftReport] = None
    # Derived, flattened text kept for backward compatibility with existing
    # consumers (chat prompt context, draft_safety_check, review payloads).
    draft_text: Optional[str] = None
    draft_citations: list[DraftCitation] = Field(default_factory=list)

    safety_result: Optional[SafetyCheckResult] = None

    trust_checks: TrustChecks = Field(default_factory=TrustChecks)
    policy_decision: Optional[ReviewDecision] = None
    approval_status: ApprovalStatus = ApprovalStatus.PENDING

    audit_trace: list[AuditLogEntry] = Field(default_factory=list)

    created_at: datetime
    updated_at: datetime

    @property
    def review_type(self) -> Optional[ReviewType]:
        return self.policy_decision.review_type if self.policy_decision else None

    @property
    def priority(self) -> Optional[Priority]:
        return self.impact_summary.priority if self.impact_summary else None
