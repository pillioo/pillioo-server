from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models.audit_log_model import AuditLog
from app.db.models.evidence_snapshot_model import TicketEvidenceSnapshot
from app.db.models.ticket import Ticket
from app.schemas.common import WorkflowStep
from app.schemas.workflow import TicketState


WORKFLOW_EVIDENCE_SNAPSHOT = "workflow_evidence"


def create_ticket_evidence_snapshot(
    *,
    db: Session,
    ticket: Ticket,
    state: TicketState,
    source_audit_log: AuditLog,
    snapshot_type: str = WORKFLOW_EVIDENCE_SNAPSHOT,
) -> TicketEvidenceSnapshot:
    """
    Persist the evidence state used by workflow routing.

    The source audit log is the sufficiency-check log that finalized this
    evidence decision. Retrieval context/trace are copied from the latest
    evidence-retrieval audit log for the same ticket.
    """
    evidence_result = state.evidence_result
    sufficiency = state.sufficiency_check
    evidence_audit_output = latest_audit_output(
        db=db,
        ticket_id=ticket.id,
        step_name=WorkflowStep.EVIDENCE_RETRIEVAL,
    )

    snapshot = TicketEvidenceSnapshot(
        ticket_id=ticket.id,
        source_audit_log_id=source_audit_log.id,
        snapshot_version=next_snapshot_version(db, ticket.id, snapshot_type=snapshot_type),
        snapshot_type=snapshot_type,
        created_workflow_step=WorkflowStep.SUFFICIENCY_CHECK.value,
        evidence_status=sufficiency.evidence_status.value if sufficiency else None,
        coverage_score=sufficiency.coverage_score if sufficiency else None,
        citations_ready=sufficiency.citations_ready if sufficiency else None,
        target_profile=(evidence_audit_output.get("retrieval_context") or {}).get("target_profile"),
        selected_chunks=(
            [chunk.model_dump(mode="json") for chunk in evidence_result.top_chunks]
            if evidence_result
            else []
        ),
        citations=(
            [citation.model_dump(mode="json") for citation in evidence_result.citations]
            if evidence_result
            else []
        ),
        sufficiency_result=sufficiency.model_dump(mode="json") if sufficiency else {},
        retrieval_trace=evidence_audit_output.get("retrieval_trace") or {},
        retrieval_plan=evidence_audit_output.get("retrieval_plan") or {},
        retrieval_context=evidence_audit_output.get("retrieval_context") or {},
    )
    db.add(snapshot)
    db.flush()
    db.refresh(snapshot)
    return snapshot


def next_snapshot_version(db: Session, ticket_id: int, *, snapshot_type: str) -> int:
    latest = (
        db.query(func.max(TicketEvidenceSnapshot.snapshot_version))
        .filter(
            TicketEvidenceSnapshot.ticket_id == ticket_id,
            TicketEvidenceSnapshot.snapshot_type == snapshot_type,
        )
        .scalar()
    )
    return int(latest or 0) + 1


def get_latest_ticket_evidence_snapshot(
    db: Session,
    ticket_id: int,
    *,
    snapshot_type: str = WORKFLOW_EVIDENCE_SNAPSHOT,
) -> TicketEvidenceSnapshot | None:
    return (
        db.query(TicketEvidenceSnapshot)
        .filter(
            TicketEvidenceSnapshot.ticket_id == ticket_id,
            TicketEvidenceSnapshot.snapshot_type == snapshot_type,
        )
        .order_by(TicketEvidenceSnapshot.snapshot_version.desc(), TicketEvidenceSnapshot.created_at.desc())
        .first()
    )


def latest_audit_output(db: Session, ticket_id: int, step_name: WorkflowStep) -> dict[str, Any]:
    log = (
        db.query(AuditLog)
        .filter(AuditLog.ticket_id == ticket_id, AuditLog.step_name == step_name.value)
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    return log.output_json if log and log.output_json else {}


def snapshot_to_response(snapshot: TicketEvidenceSnapshot, public_ticket_id: str) -> dict[str, Any]:
    selected_chunks = snapshot.selected_chunks or []
    sufficiency = apply_recall_notice_identifier_guard(snapshot.sufficiency_result or {}, selected_chunks)
    retrieval_trace = snapshot.retrieval_trace or {}
    retrieval_plan = snapshot.retrieval_plan or {}
    if not retrieval_plan and retrieval_trace.get("targets"):
        retrieval_plan = {"targets": retrieval_trace["targets"]}
    return {
        "ticket_id": public_ticket_id,
        "snapshot_id": snapshot.id,
        "snapshot_version": snapshot.snapshot_version,
        "snapshot_type": snapshot.snapshot_type,
        "source_audit_log_id": snapshot.source_audit_log_id,
        "created_workflow_step": snapshot.created_workflow_step,
        "created_at": snapshot.created_at,
        "evidence_status": sufficiency.get("evidence_status", snapshot.evidence_status),
        "coverage_score": snapshot.coverage_score,
        "citations_ready": snapshot.citations_ready,
        "target_profile": snapshot.target_profile,
        "required_sources": sufficiency.get("required_sources", []),
        "found_sources": sufficiency.get("found_sources", []),
        "missing_sources": sufficiency.get("missing_sources", []),
        "weak_sources": sufficiency.get("weak_sources", []),
        "failure_reasons": sufficiency.get("failure_reasons", []),
        "selected_chunks": selected_chunks,
        "citations": snapshot.citations or [],
        "sufficiency_result": sufficiency,
        "retrieval_context": snapshot.retrieval_context or {},
        "retrieval_plan": retrieval_plan,
        "retrieval_trace": retrieval_trace,
    }


def legacy_ticket_evidence_to_response(
    ticket: Ticket,
    *,
    evidence_audit_output: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Read-only fallback for tickets processed before durable snapshots existed.

    This preserves the frontend evidence view for legacy tickets without
    creating a new snapshot row as a side effect of GET.
    """
    evidence_audit_output = evidence_audit_output or {}
    evidence = ticket.evidence_result or {}
    retrieval_trace = evidence_audit_output.get("retrieval_trace") or {}
    selected_chunks = enrich_legacy_selected_chunks(
        evidence.get("top_chunks", []),
        retrieval_trace.get("selected_chunks", []),
    )
    sufficiency = apply_recall_notice_identifier_guard(ticket.sufficiency_check or {}, selected_chunks)
    retrieval_plan = evidence_audit_output.get("retrieval_plan") or {}
    if not retrieval_plan and retrieval_trace.get("targets"):
        retrieval_plan = {"targets": retrieval_trace["targets"]}
    return {
        "ticket_id": ticket.ticket_id,
        "snapshot_id": None,
        "snapshot_version": None,
        "snapshot_type": "legacy_ticket_evidence",
        "source_audit_log_id": None,
        "created_workflow_step": None,
        "created_at": None,
        "evidence_status": sufficiency.get("evidence_status"),
        "coverage_score": sufficiency.get("coverage_score"),
        "citations_ready": sufficiency.get("citations_ready"),
        "target_profile": (evidence_audit_output.get("retrieval_context") or {}).get("target_profile"),
        "required_sources": sufficiency.get("required_sources", []),
        "found_sources": sufficiency.get("found_sources", []),
        "missing_sources": sufficiency.get("missing_sources", []),
        "weak_sources": sufficiency.get("weak_sources", []),
        "failure_reasons": sufficiency.get("failure_reasons", []),
        "selected_chunks": selected_chunks,
        "citations": evidence.get("citations", []),
        "sufficiency_result": sufficiency,
        "retrieval_context": evidence_audit_output.get("retrieval_context") or {},
        "retrieval_plan": retrieval_plan,
        "retrieval_trace": retrieval_trace,
        "warnings": [
            {
                "source": "evidence_snapshot",
                "message": "No durable snapshot row exists; response was reconstructed from legacy ticket evidence fields.",
            }
        ],
    }


def enrich_legacy_selected_chunks(
    selected_chunks: list[dict[str, Any]],
    trace_chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    trace_by_key = {
        (
            chunk.get("document_type"),
            chunk.get("section"),
            chunk.get("source_path"),
        ): chunk
        for chunk in trace_chunks
    }
    enriched: list[dict[str, Any]] = []
    for chunk in selected_chunks:
        item = dict(chunk)
        trace = trace_by_key.get(
            (
                item.get("document_type"),
                item.get("section"),
                item.get("source_path"),
            )
        )
        if trace:
            for key in ("filter_level", "matched_identifiers", "rank_reasons", "rank_score"):
                if key not in item:
                    item[key] = trace.get(key)
        enriched.append(item)
    return enriched


def apply_recall_notice_identifier_guard(
    sufficiency: dict[str, Any],
    selected_chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    guarded = dict(sufficiency)
    required = set(guarded.get("required_sources") or [])
    found = set(guarded.get("found_sources") or [])
    if "recall_notice" not in required or "recall_notice" not in found:
        return guarded

    recall_chunks = [chunk for chunk in selected_chunks if chunk.get("document_type") == "recall_notice"]
    has_strong_identifier = any(
        STRONG_RECALL_NOTICE_IDENTIFIER_KEYS & set((chunk.get("matched_identifiers") or {}).keys())
        for chunk in recall_chunks
    )
    if has_strong_identifier:
        return guarded

    weak_sources = list(guarded.get("weak_sources") or [])
    if "recall_notice" not in weak_sources:
        weak_sources.append("recall_notice")
    failure_reasons = list(guarded.get("failure_reasons") or [])
    if not any(reason.get("reason") == "recall_notice_identifier_mismatch" for reason in failure_reasons):
        failure_reasons.append(
            {
                "reason": "recall_notice_identifier_mismatch",
                "document_type": "recall_notice",
                "message": "Recall notice evidence did not match recall number, NDC, lot, or normalized drug name.",
                "filter_levels": sorted({chunk.get("filter_level") for chunk in recall_chunks if chunk.get("filter_level")}),
            }
        )
    guarded["weak_sources"] = weak_sources
    guarded["failure_reasons"] = failure_reasons
    guarded["evidence_status"] = "insufficient"
    guarded["needs_evidence_review"] = True
    return guarded


STRONG_RECALL_NOTICE_IDENTIFIER_KEYS = frozenset(
    {"recall_number", "ndc", "lot", "normalized_drug_name", "rxnorm_rxcui"}
)
