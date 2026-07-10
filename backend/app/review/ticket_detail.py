"""
Consolidated ticket detail view for the frontend workflow-execution screen.

Combines ticket state + per-step audit trail into a single response so the
frontend doesn't have to stitch together /tickets/{id}/run,
/tickets/{id}/evidence-trace, and /audit/{id} on its own.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models.audit_log_model import AuditLog
from app.db.models.ticket import Ticket
from app.schemas.common import WorkflowStep
from app.workflow.state import can_rerun_workflow

# The steps run_ticket_workflow actually executes, in order.
WORKFLOW_STEPS: list[WorkflowStep] = [
    WorkflowStep.INVENTORY_MATCH,
    WorkflowStep.EVIDENCE_RETRIEVAL,
    WorkflowStep.SUFFICIENCY_CHECK,
    WorkflowStep.DRAFT_GENERATION,
    WorkflowStep.SAFETY_CHECK,
    WorkflowStep.POLICY_AGGREGATION,
]


def build_ticket_detail(db: Session, ticket: Ticket) -> dict:
    logs = (
        db.query(AuditLog)
        .filter(AuditLog.ticket_id == ticket.id)
        .order_by(AuditLog.created_at.asc())
        .all()
    )

    # Later entries win — a retried step can have more than one audit row.
    latest_by_step = {log.step_name: log for log in logs}

    steps = []
    failure_reason = None
    for step in WORKFLOW_STEPS:
        log = latest_by_step.get(step.value)
        if log is None:
            steps.append(
                {
                    "step": step.value,
                    "status": "pending",
                    "duration_ms": None,
                    "reason": None,
                    "completed_at": None,
                }
            )
            continue

        output = log.output_json or {}
        step_status = output.get("step_status", "succeeded")
        reason = None
        if step_status == "failed":
            reason = output.get("error_message")
            failure_reason = f"{step.value}: {reason}" if reason else step.value
        elif step_status == "skipped":
            reason = output.get("reason")

        steps.append(
            {
                "step": step.value,
                "status": step_status,
                "duration_ms": log.duration_ms,
                "reason": reason,
                "completed_at": log.created_at,
            }
        )

    return {
        "ticket_id": ticket.ticket_id,
        "status": ticket.status,
        "workflow_stage": ticket.workflow_stage,
        "drug_name": ticket.drug_name,
        "ndc": ticket.ndc,
        "lot": ticket.lot,
        "classification": ticket.classification,
        "recall_number": ticket.recall_number,
        "priority": ticket.priority,
        "review_type": ticket.review_type,
        "created_at": ticket.created_at,
        "updated_at": ticket.updated_at or ticket.created_at,
        "can_rerun": can_rerun_workflow(ticket.status),
        "failure_reason": failure_reason,
        "steps": steps,
    }
