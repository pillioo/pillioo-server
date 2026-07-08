"""
P4 - Approval Handler

Handles pharmacist approval decisions:
    - approve: saves final_v1, updates status to approved
    - reject: updates status to rejected with required comment
    - revise: re-runs safety check on revised draft, saves draft_v2

All decisions are recorded in audit_logs.
"""

from sqlalchemy.orm import Session

from app.db.models.approval_model import Approval
from app.event.safety import draft_safety_check
from app.report.versioning import save_report_version
from app.audit.logger import write_audit_log
from app.schemas.common import ApprovalStatus, ReportVersionTag, WorkflowStep
from app.schemas.review import ApproveRequest, RejectRequest, ReviseRequest


def handle_approve(
    db: Session,
    ticket_id: int,
    public_ticket_id: str,
    request: ApproveRequest,
    current_draft: str,
) -> dict:
    """
    약사 승인 처리.

    처리 내용:
        1. approvals 테이블에 승인 기록 저장
        2. final_v1 보고서 버전 저장
        3. audit log 기록

    Args:
        db: DB 세션
        ticket_id: 승인할 티켓 ID
        request: 승인 요청 (reviewer, comment)
        current_draft: 승인된 보고서 내용

    Returns:
        dict: 승인 결과

    예시 응답:
        {
            "ticket_id": "T-001",
            "approval_status": "approved",
            "final_report_version": "final_v1"
        }
    """
    import time
    start = time.time()

    # 1. 승인 기록 저장
    approval = Approval(
        ticket_id=ticket_id,
        reviewer=request.reviewer,
        status=ApprovalStatus.APPROVED.value,
        comment=request.comment,
    )
    db.add(approval)
    db.flush() 

    # 2. final_v1 저장
    save_report_version(
        db=db,
        ticket_id=ticket_id,
        version_tag=ReportVersionTag.FINAL_V1,
        content=current_draft,
        created_by=request.reviewer,
    )

    # 3. audit log 기록
    duration_ms = int((time.time() - start) * 1000)
    write_audit_log(
        db=db,
        ticket_id=ticket_id,
        step_name=WorkflowStep.APPROVAL_DECISION,
        input_json={"reviewer": request.reviewer, "decision": "approve"},
        output_json={"approval_status": "approved", "version": "final_v1"},
        duration_ms=duration_ms,
    )
    db.commit()
    
    return {
        "ticket_id": public_ticket_id,
        "approval_status": ApprovalStatus.APPROVED.value,
        "final_report_version": ReportVersionTag.FINAL_V1.value,
    }


def handle_reject(
    db: Session,
    ticket_id: int,
    public_ticket_id: str,
    request: RejectRequest,
) -> dict:
    """
    약사 반려 처리.

    처리 내용:
        1. approvals 테이블에 반려 기록 저장
        2. audit log 기록

    Args:
        db: DB 세션
        ticket_id: 반려할 티켓 ID
        request: 반려 요청 (reviewer, comment 필수)

    Returns:
        dict: 반려 결과

    예시 응답:
        {
            "ticket_id": "T-001",
            "approval_status": "rejected",
            "comment": "재고 확인 필요"
        }
    """
    import time
    start = time.time()

    # 1. 반려 기록 저장
    approval = Approval(
        ticket_id=ticket_id,
        reviewer=request.reviewer,
        status=ApprovalStatus.REJECTED.value,
        comment=request.comment,
    )
    db.add(approval)
    db.flush()

    # 2. audit log 기록
    duration_ms = int((time.time() - start) * 1000)
    write_audit_log(
        db=db,
        ticket_id=ticket_id,
        step_name=WorkflowStep.APPROVAL_DECISION,
        input_json={"reviewer": request.reviewer, "decision": "reject"},
        output_json={"approval_status": "rejected", "comment": request.comment},
        duration_ms=duration_ms,
    )
    db.commit()

    return {
        "ticket_id": public_ticket_id,
        "approval_status": ApprovalStatus.REJECTED.value,
        "comment": request.comment,
    }


def handle_revise(
    db: Session,
    ticket_id: int,
    public_ticket_id: str,
    request: ReviseRequest,
) -> dict:
    """
    약사 수정 요청 처리.

    처리 내용:
        1. 수정된 초안을 safety check 재실행
        2. 통과하면 draft_v2 저장
        3. 차단 문장 있으면 action_review payload 재구성 필요
        4. audit log 기록

    Args:
        db: DB 세션
        ticket_id: 수정 요청 티켓 ID
        request: 수정 요청 (reviewer, revised_draft)

    Returns:
        dict: 수정 처리 결과

    예시 응답 (통과):
        {
            "ticket_id": "T-001",
            "approval_status": "pending",
            "new_version": "draft_v2",
            "safety_check_passed": True,
            "blocked_sentences": []
        }

    예시 응답 (재차단):
        {
            "ticket_id": "T-001",
            "approval_status": "pending",
            "new_version": None,
            "safety_check_passed": False,
            "blocked_sentences": [...]
        }
    """
    import time
    start = time.time()

    # 1. safety check 재실행
    safety_result = draft_safety_check(request.revised_draft)

    new_version = None

    if not safety_result.needs_action_review:
        # 2. 안전하면 draft_v2 저장
        save_report_version(
            db=db,
            ticket_id=ticket_id,
            version_tag=ReportVersionTag.DRAFT_V2,
            content=request.revised_draft,
            created_by=request.reviewer,
        )
        new_version = ReportVersionTag.DRAFT_V2.value

    # 3. audit log 기록
    duration_ms = int((time.time() - start) * 1000)
    write_audit_log(
        db=db,
        ticket_id=ticket_id,
        step_name=WorkflowStep.APPROVAL_DECISION,
        input_json={
            "reviewer": request.reviewer,
            "decision": "revise",
            "revised_draft": request.revised_draft,
        },
        output_json={
            "safety_check_passed": not safety_result.needs_action_review,
            "blocked_sentences": [
                b.model_dump() for b in safety_result.blocked_sentences
            ],
            "new_version": new_version,
        },
        duration_ms=duration_ms,
    )
    db.commit()

    return {
        "ticket_id": public_ticket_id,
        "approval_status": ApprovalStatus.PENDING.value,
        "new_version": new_version,
        "safety_check_passed": not safety_result.needs_action_review,
        "blocked_sentences": safety_result.blocked_sentences,
    }
