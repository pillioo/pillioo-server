from __future__ import annotations

from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models.audit_log_model import AuditLog
from app.db.models.ticket import Ticket
from app.schemas.common import WorkflowStep


def latest_audit_output(db: Session, ticket_id: int, step_name: WorkflowStep) -> tuple[dict[str, Any], dict[str, Any] | None]:
    try:
        log = (
            db.query(AuditLog)
            .filter(AuditLog.ticket_id == ticket_id, AuditLog.step_name == step_name.value)
            .order_by(AuditLog.created_at.desc())
            .first()
        )
    except SQLAlchemyError as exc:
        # Evidence trace is a debug/read endpoint. A missing or drifted audit
        # table should not hide ticket-level evidence state that is still usable
        # for Swagger/manual verification.
        return {}, {
            "source": "audit_log",
            "step_name": step_name.value,
            "error_type": type(exc).__name__,
            "message": str(exc),
        }
    return (log.output_json if log and log.output_json else {}), None


def build_ticket_evidence_trace(
    ticket: Ticket,
    *,
    evidence_audit_output: dict[str, Any] | None = None,
    gate_audit_output: dict[str, Any] | None = None,
    policy_audit_output: dict[str, Any] | None = None,
    warnings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    evidence_audit_output = evidence_audit_output or {}
    gate_audit_output = gate_audit_output or {}
    policy_audit_output = policy_audit_output or {}
    sufficiency = ticket.sufficiency_check or {}
    evidence = ticket.evidence_result or {}

    # PR2 is intentionally read-only: trace data is reconstructed from the
    # ticket JSON columns plus audit logs. Durable snapshot persistence starts
    # in the later evidence snapshot PR.
    retrieval_trace = evidence_audit_output.get("retrieval_trace") or {}
    return {
        "ticket_id": ticket.ticket_id,
        "status": ticket.status,
        "review_type": ticket.review_type,
        "evidence_status": sufficiency.get("evidence_status"),
        "coverage_score": sufficiency.get("coverage_score"),
        "required_sources": sufficiency.get("required_sources", []),
        "found_sources": sufficiency.get("found_sources", []),
        "missing_sources": sufficiency.get("missing_sources", []),
        "weak_sources": sufficiency.get("weak_sources", []),
        "failure_reasons": sufficiency.get("failure_reasons", []),
        "citations_ready": sufficiency.get("citations_ready"),
        "warnings": warnings or [],
        "gate": {
            "gate_status": gate_audit_output.get("gate_status"),
            "can_generate_draft": gate_audit_output.get("can_generate_draft"),
            "skip_reason": gate_audit_output.get("skip_reason"),
        },
        "routing": {
            "review_type": policy_audit_output.get("review_type") or ticket.review_type,
            "final_routing_reason": policy_audit_output.get("final_routing_reason"),
            "reasons": policy_audit_output.get("reasons", []),
        },
        "retrieval": {
            "query": evidence_audit_output.get("query"),
            "top_k": evidence_audit_output.get("top_k"),
            "retrieval_context": evidence_audit_output.get("retrieval_context", {}),
            "filter_expressions": evidence_audit_output.get("filter_expressions", []),
            "trace": retrieval_trace,
        },
        "top_chunks": evidence.get("top_chunks", []),
        "citations": evidence.get("citations", []),
    }
