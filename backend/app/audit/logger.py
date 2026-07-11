"""
P4 - Audit Logger

Records each workflow step's input, output, and duration.
Called by the Orchestrator at every processing step.
Enables full audit trail: "why did this ticket go to evidence_review?"
"""

from sqlalchemy.orm import Session

from app.db.models.audit_log_model import AuditLog
from app.schemas.common import WorkflowStep
from app.schemas.workflow import AuditLogEntry


# Human-readable titles per step -- falls back to a title-cased step_name
# for any step not listed here (defensive default, not meant to be hit).
_STEP_TITLES: dict[str, str] = {
    WorkflowStep.EVENT_NORMALIZED.value: "Event Normalized",
    WorkflowStep.TICKET_CREATED.value: "Ticket Created",
    WorkflowStep.INVENTORY_MATCH.value: "Inventory Match",
    WorkflowStep.IMPACT_ASSESSMENT.value: "Impact Assessment",
    WorkflowStep.EVIDENCE_ROUTING.value: "Evidence Routing",
    WorkflowStep.EVIDENCE_RETRIEVAL.value: "Evidence Retrieval",
    WorkflowStep.SUFFICIENCY_CHECK.value: "Sufficiency Check",
    WorkflowStep.DRAFT_GENERATION.value: "Draft Generation",
    WorkflowStep.SAFETY_CHECK.value: "Safety Check",
    WorkflowStep.INVENTORY_QUALITY_CHECK.value: "Inventory Quality Check",
    WorkflowStep.RAG_QUALITY_CHECK.value: "RAG Quality Check",
    WorkflowStep.POLICY_AGGREGATION.value: "Policy Aggregation",
    WorkflowStep.HITL_ROUTED.value: "Routed for Review",
    WorkflowStep.APPROVAL_DECISION.value: "Approval Decision",
}

# status -> severity, same status vocabulary already used by
# app/review/ticket_detail.py's per-step "steps" array (output_json's
# "step_status" key), so the two views of the same data stay consistent.
_STATUS_SEVERITY: dict[str, str] = {
    "succeeded": "info",
    "failed": "error",
    "skipped": "warning",
}


def derive_display_fields(step_name: str, output_json: dict) -> dict:
    """
    Derives frontend-timeline-friendly title/message/severity/status from a
    raw audit log row, without needing per-step bespoke logic beyond the
    title lookup and the existing step_status/error_message/reason
    convention (see app/review/ticket_detail.py for the sibling usage of
    that same convention).
    """
    output = output_json or {}
    status = output.get("step_status", "succeeded")
    title = _STEP_TITLES.get(step_name, step_name.replace("_", " ").title())
    severity = _STATUS_SEVERITY.get(status, "info")

    if status == "failed":
        reason = output.get("error_message")
        message = f"{title} failed: {reason}" if reason else f"{title} failed."
    elif status == "skipped":
        reason = output.get("reason")
        message = f"{title} skipped: {reason}" if reason else f"{title} skipped."
    else:
        message = f"{title} completed successfully."

    return {"title": title, "message": message, "severity": severity, "status": status}


def write_audit_log(
    db: Session,
    ticket_id: int,
    step_name: WorkflowStep,
    input_json: dict,
    output_json: dict,
    duration_ms: int,
) -> AuditLog:
    """
    워크플로우 단계별 처리 결과를 audit_logs 테이블에 저장.

    Orchestrator가 각 단계마다 호출.

    Args:
        db: DB 세션
        ticket_id: 티켓 ID
        step_name: 워크플로우 단계명 (WorkflowStep enum)
        input_json: 해당 단계 입력값
        output_json: 해당 단계 출력값
        duration_ms: 처리 소요 시간 (밀리초)

    Returns:
        AuditLog: 저장된 audit log 레코드

    예시:
        write_audit_log(
            db=db,
            ticket_id="T-001",
            step_name=WorkflowStep.SAFETY_CHECK,
            input_json={"draft_text": "즉시 투여를 중단하세요."},
            output_json={"blocked_sentences": [...], "needs_action_review": True},
            duration_ms=280,
        )
    """
    entry = AuditLog(
        ticket_id=ticket_id,
        step_name=step_name.value,
        input_json=input_json,
        output_json=output_json,
        duration_ms=duration_ms,
    )
    db.add(entry)
    db.flush() 
    db.refresh(entry)
    return entry


def get_audit_trace(db: Session, ticket_id: int) -> list[AuditLogEntry]:
    """
    특정 티켓의 전체 처리 기록 조회.

    GET /audit/{ticket_id} 에서 호출.

    Args:
        db: DB 세션
        ticket_id: 조회할 티켓 ID

    Returns:
        list[AuditLogEntry]: 처리 단계별 기록 목록 (시간순)

    예시 응답:
        [
            {
                "step_name": "inventory_match",
                "input_json": {...},
                "output_json": {...},
                "timestamp": "2026-06-17T10:22:30",
                "duration_ms": 124
            },
            {
                "step_name": "safety_check",
                "input_json": {...},
                "output_json": {...},
                "timestamp": "2026-06-17T10:23:11",
                "duration_ms": 280
            }
        ]
    """
    # AuditLog has no `timestamp` column (only created_at/updated_at via
    # TimeStampedModel) -- ordering by AuditLog.timestamp raised
    # AttributeError on every call. No test caught this because there was
    # no coverage at all for get_audit_trace / GET /audit/{ticket_id}.
    logs = (
        db.query(AuditLog)
        .filter(AuditLog.ticket_id == ticket_id)
        .order_by(AuditLog.created_at.asc())
        .all()
    )

    return [
        AuditLogEntry(
            ticket_id=log.ticket.ticket_id if log.ticket else str(log.ticket_id),
            step_name=log.step_name,
            input_json=log.input_json,
            output_json=log.output_json,
            timestamp=log.created_at,
            duration_ms=log.duration_ms,
            **derive_display_fields(log.step_name, log.output_json),
        )
        for log in logs
    ]
