from __future__ import annotations

from enum import Enum

from app.schemas.common import TicketStatus


class WorkflowStage(str, Enum):
    PENDING_INVENTORY = "PENDING_INVENTORY"
    PENDING_EVIDENCE = "PENDING_EVIDENCE"
    PENDING_DRAFT = "PENDING_DRAFT"
    PENDING_SAFETY = "PENDING_SAFETY"
    PENDING_POLICY_AGGREGATION = "PENDING_POLICY_AGGREGATION"
    PENDING_REVIEW = "PENDING_REVIEW"
    PENDING_MANUAL_REVIEW = "PENDING_MANUAL_REVIEW"
    CLOSED = "CLOSED"
    FAILED = "FAILED"


def stage_for_status(status: TicketStatus) -> WorkflowStage:
    if status == TicketStatus.CREATED:
        return WorkflowStage.PENDING_INVENTORY
    if status == TicketStatus.INVENTORY_CHECKED:
        return WorkflowStage.PENDING_EVIDENCE
    if status == TicketStatus.EVIDENCE_RETRIEVED:
        return WorkflowStage.PENDING_DRAFT
    if status == TicketStatus.DRAFT_GENERATED:
        return WorkflowStage.PENDING_SAFETY
    if status == TicketStatus.SAFETY_CHECKED:
        return WorkflowStage.PENDING_POLICY_AGGREGATION
    if status == TicketStatus.REVIEW_ROUTED:
        return WorkflowStage.PENDING_REVIEW
    if status == TicketStatus.WORKFLOW_FAILED:
        return WorkflowStage.PENDING_MANUAL_REVIEW
    if status in {TicketStatus.APPROVED, TicketStatus.REJECTED, TicketStatus.CLOSED}:
        return WorkflowStage.CLOSED
    return WorkflowStage.PENDING_MANUAL_REVIEW
