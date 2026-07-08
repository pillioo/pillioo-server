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
    logs = (
        db.query(AuditLog)
        .filter(AuditLog.ticket_id == ticket_id)
        .order_by(AuditLog.timestamp.asc())
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
        )
        for log in logs
    ]
