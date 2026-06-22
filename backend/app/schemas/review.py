from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field

from app.schemas.common import (
    ApprovalStatus,
    Classification,
    Department,
    DocumentType,
    EventType,
    Priority,
    ReviewType,
)
from app.schemas.event import BlockedSentence
from app.schemas.evidence import Citation


class TicketSummary(BaseModel):
    drug_name: str
    event_type: EventType
    classification: Optional[Classification] = None
    priority: Optional[Priority] = None


class IdentityIssue(BaseModel):
    input_ndc: str
    matched_ndc: Optional[str] = None
    match_confidence: float = Field(..., ge=0.0, le=1.0)
    reason: str


class EvidenceIssue(BaseModel):
    required_sources: list[DocumentType]
    found_sources: list[DocumentType]
    missing_sources: list[DocumentType]
    coverage_score: float = Field(..., ge=0.0, le=1.0)


class IdentityReviewPayload(BaseModel):
    ticket_id: str
    review_type: Literal[ReviewType.IDENTITY_REVIEW] = ReviewType.IDENTITY_REVIEW
    approval_status: ApprovalStatus
    summary: TicketSummary
    identity_issue: IdentityIssue
    affected_departments: list[Department]
    total_quantity: int = Field(..., ge=0)


class EvidenceReviewPayload(BaseModel):
    ticket_id: str
    review_type: Literal[ReviewType.EVIDENCE_REVIEW] = ReviewType.EVIDENCE_REVIEW
    approval_status: ApprovalStatus
    summary: TicketSummary
    evidence_issue: EvidenceIssue
    draft_text: str
    citations: list[Citation] = Field(default_factory=list)


class ActionReviewPayload(BaseModel):
    ticket_id: str
    review_type: Literal[ReviewType.ACTION_REVIEW] = ReviewType.ACTION_REVIEW
    approval_status: ApprovalStatus
    summary: TicketSummary
    blocked_sentences: list[BlockedSentence]
    original_draft: str
    revised_draft: str
    citations: list[Citation] = Field(default_factory=list)


class FinalApprovalPayload(BaseModel):
    ticket_id: str
    review_type: Literal[ReviewType.FINAL_APPROVAL] = ReviewType.FINAL_APPROVAL
    approval_status: ApprovalStatus
    summary: TicketSummary
    draft_text: str
    citations: list[Citation] = Field(default_factory=list)
    evidence_coverage: float = Field(..., ge=0.0, le=1.0)
    inventory_confidence: float = Field(..., ge=0.0, le=1.0)


ReviewPayload = Annotated[
    Union[
        IdentityReviewPayload,
        EvidenceReviewPayload,
        ActionReviewPayload,
        FinalApprovalPayload,
    ],
    Field(discriminator="review_type"),
]


class ApproveRequest(BaseModel):
    reviewer: str
    comment: Optional[str] = None


class RejectRequest(BaseModel):
    reviewer: str
    comment: str = Field(..., min_length=1, description="Rejection reason is required.")


class ReviseRequest(BaseModel):
    reviewer: str
    revised_draft: str = Field(..., min_length=1)