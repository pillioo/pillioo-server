"""FastAPI endpoints for RAG/evidence debugging.

These endpoints expose read-only operational views of evidence retrieval state.
Internal retrieval planning stays in app.rag.router; durable evidence snapshot
persistence belongs to the later snapshot workflow.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.rag.evidence_snapshot import (
    get_latest_ticket_evidence_snapshot,
    legacy_ticket_evidence_to_response,
    snapshot_to_response,
)
from app.rag.evidence_trace import build_ticket_evidence_trace, latest_audit_output
from app.review.tickets import get_ticket_by_public_id
from app.schemas.common import WorkflowStep


router = APIRouter(tags=["rag"])


@router.get("/tickets/{ticket_id}/evidence")
async def get_ticket_evidence_snapshot(
    ticket_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        ticket = get_ticket_by_public_id(db, ticket_id)
        snapshot = get_latest_ticket_evidence_snapshot(db, ticket.id)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "error_code": "DATABASE_UNAVAILABLE",
                "message": "Database connection is unavailable.",
                "detail": {
                    "ticket_id": ticket_id,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
            },
        ) from exc

    if snapshot is None and (ticket.evidence_result or ticket.sufficiency_check):
        evidence_audit_output, _warning = latest_audit_output(db, ticket.id, WorkflowStep.EVIDENCE_RETRIEVAL)
        return legacy_ticket_evidence_to_response(ticket, evidence_audit_output=evidence_audit_output)

    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "EVIDENCE_SNAPSHOT_NOT_FOUND",
                "message": "No workflow evidence snapshot exists for this ticket.",
                "detail": {"ticket_id": ticket_id},
            },
        )

    return snapshot_to_response(snapshot, ticket.ticket_id)


@router.get("/tickets/{ticket_id}/evidence-trace")
async def get_ticket_evidence_trace(
    ticket_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        ticket = get_ticket_by_public_id(db, ticket_id)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "error_code": "DATABASE_UNAVAILABLE",
                "message": "Database connection is unavailable.",
                "detail": {
                    "ticket_id": ticket_id,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
            },
        ) from exc
    evidence_audit_output, evidence_warning = latest_audit_output(db, ticket.id, WorkflowStep.EVIDENCE_RETRIEVAL)
    gate_audit_output, gate_warning = latest_audit_output(db, ticket.id, WorkflowStep.SUFFICIENCY_CHECK)
    policy_audit_output, policy_warning = latest_audit_output(db, ticket.id, WorkflowStep.POLICY_AGGREGATION)
    return build_ticket_evidence_trace(
        ticket,
        evidence_audit_output=evidence_audit_output,
        gate_audit_output=gate_audit_output,
        policy_audit_output=policy_audit_output,
        warnings=[warning for warning in [evidence_warning, gate_warning, policy_warning] if warning],
    )
