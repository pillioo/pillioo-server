"""API boundary schemas used by workflow routes and evaluation runner."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import (
    ApprovalStatus,
    Classification,
    EvidenceStatus,
    Priority,
    ReportVersionTag,
    ReviewType,
    TicketStatus,
)
from app.schemas.event import BlockedSentence
from app.schemas.evidence import Citation


class EventUploadRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "recall_number": "D-TEST-2026-001",
                    "product_description": "Midazolam HCl Injection 1 mg/mL vial",
                    "reason_for_recall": "Subpotent drug product",
                    "classification": "class_i",
                    "product_ndc": "00641-6014-41",
                    "lot_number": "LOT-A",
                    "recall_initiation_date": "2026-07-09",
                    "status": "ongoing",
                }
            ]
        }
    )

    recall_number: str
    product_description: str
    reason_for_recall: str
    classification: Optional[Classification] = None
    product_ndc: str = Field(
        ...,
        description="Raw FDA NDC format, including hyphens if present.",
    )
    lot_number: Optional[str] = None
    recall_initiation_date: Optional[date] = None
    status: str = Field(..., description="Raw FDA status value.")


class EventUploadResponse(BaseModel):
    event_id: str
    duplicated: bool
    ticket_id: Optional[str] = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def check_ticket_id_consistency(self) -> "EventUploadResponse":
        if self.duplicated and self.ticket_id is not None:
            raise ValueError("ticket_id must be empty when duplicated is true.")

        if not self.duplicated and self.ticket_id is None:
            raise ValueError("ticket_id is required when duplicated is false.")
        return self


class WorkflowRunResponse(BaseModel):
    ticket_id: str
    status: TicketStatus
    message: str = "workflow started"


class WorkflowStepStatus(BaseModel):
    step: str
    status: str  # "pending" | "succeeded" | "failed" | "skipped"
    duration_ms: Optional[int] = None
    reason: Optional[str] = None
    completed_at: Optional[datetime] = None


class TicketDetailResponse(BaseModel):
    ticket_id: str
    status: TicketStatus
    workflow_stage: str
    drug_name: str
    ndc: str
    lot: Optional[str] = None
    classification: Optional[Classification] = None
    recall_number: Optional[str] = None
    priority: Optional[str] = None
    review_type: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    can_rerun: bool
    failure_reason: Optional[str] = None
    steps: list[WorkflowStepStatus]


class PendingApprovalItem(BaseModel):
    # public string id (e.g. "T-001"), consistent with every other endpoint
    # in app/review/router.py. The internal integer FK previously lived here
    # under this same field name -- see internal_id below.
    ticket_id: str
    internal_id: int
    drug_name: str
    recall_number: Optional[str] = None
    classification: Optional[Classification] = None
    review_type: Optional[ReviewType] = None
    priority: Optional[Priority] = None
    approval_status: Optional[str] = None
    created_at: datetime


class TicketListItem(BaseModel):
    ticket_id: str
    status: TicketStatus
    workflow_stage: str
    drug_name: str
    ndc: str
    lot: Optional[str] = None
    classification: Optional[Classification] = None
    recall_number: Optional[str] = None
    priority: Optional[str] = None
    review_type: Optional[str] = None
    created_at: datetime
    # Ticket.updated_at has onupdate=func.now() but no insert-time default
    # (see app/db/base.py TimeStampedModel), so it stays NULL in the DB until
    # a ticket's first UPDATE (e.g. the first workflow run). A ticket that
    # was only ever uploaded, never run, legitimately has no updated_at yet.
    updated_at: Optional[datetime] = None


class TicketListResponse(BaseModel):
    items: list[TicketListItem]
    total: int = Field(..., ge=0, description="Total matching tickets, ignoring limit/offset")
    limit: int
    offset: int


class ApproveResponse(BaseModel):
    ticket_id: str
    approval_status: ApprovalStatus = ApprovalStatus.APPROVED
    final_report_version: ReportVersionTag = ReportVersionTag.FINAL_V1


class RejectResponse(BaseModel):
    ticket_id: str
    approval_status: ApprovalStatus = ApprovalStatus.REJECTED
    comment: str


class ReviseResponse(BaseModel):
    ticket_id: str
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    new_version: ReportVersionTag = ReportVersionTag.DRAFT_V2
    safety_check_passed: bool
    blocked_sentences: list[BlockedSentence] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_consistency(self) -> "ReviseResponse":
        if not self.safety_check_passed and not self.blocked_sentences:
            raise ValueError(
                "blocked_sentences is required when safety_check_passed is false."
            )
        if self.safety_check_passed and self.blocked_sentences:
            raise ValueError(
                "blocked_sentences must be empty when safety_check_passed is true."
            )

        return self


class ChatRequest(BaseModel):
    # ticket_id is intentionally not a field here: it is always supplied via
    # the POST /chat/{ticket_id} path parameter, so a duplicate body field
    # would only invite a client to send a mismatched value.
    user_query: str = Field(..., min_length=1, description="Pharmacist's question")
    session_id: Optional[str] = Field(
        default=None, min_length=1, description="Existing session ID (reuses the ticket's session if omitted)"
    )
    top_k: int = Field(default=5, ge=1, le=20, description="Number of evidence chunks to retrieve")


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    sources: list[Citation] = Field(default_factory=list)
    intent: Optional[str] = None
    standalone_query: Optional[str] = None
    answer_mode: Optional[str] = None
    target_profile: Optional[str] = None
    evidence_status: Optional[str] = None
    retrieved_evidence_scope: Optional[str] = None
    answer_support_level: Optional[str] = None


class HealthCheckResponse(BaseModel):
    status: str
    timestamp: datetime
    services: dict[str, str] = Field(default_factory=dict)


class EvalExpected(BaseModel):
    review_type: ReviewType
    evidence_status: EvidenceStatus
    expects_blocked_sentences: bool
    priority: Priority
    urgent: bool
    final_status: TicketStatus


class EvalScenario(BaseModel):
    scenario_id: str
    description: str
    input_event: EventUploadRequest
    expected: EvalExpected


class EvalResult(BaseModel):
    scenario_id: str
    passed: bool
    expected_review_type: ReviewType
    actual_review_type: ReviewType
    expected_evidence_status: EvidenceStatus
    actual_evidence_status: EvidenceStatus
    expected_has_blocked_sentences: bool
    actual_has_blocked_sentences: bool
    workflow_steps_completed: int = Field(..., ge=0)
    duration_ms: int = Field(..., ge=0)
    failure_reason: Optional[str] = None


class EventFeedItem(BaseModel):
    event_id: str
    source: str
    is_duplicate: Optional[bool] = None
    product_description: str
    recall_reason: Optional[str] = None
    ticket_id: Optional[str] = None
    can_run: bool = False
    raw_event_data: dict = Field(default_factory=dict)
    created_at: datetime


class EventLatestResponse(BaseModel):
    events: list[EventFeedItem]
    total_count: int