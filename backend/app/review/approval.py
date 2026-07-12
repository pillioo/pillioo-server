"""
P4 - Approval Handler

Handles pharmacist approval decisions:
    - approve: freezes the latest draft as final_v1 (no LLM regeneration),
      updates status to approved
    - reject: updates status to rejected with required comment
    - revise (pharmacist-edited): persists the pharmacist's own text as
      draft_v2 after a safety re-check
    - revise (system-revised): applies a bounded LLM edit to the latest
      structured draft on the pharmacist's behalf, driven by reviewer
      feedback or a flagged safety issue, then safety re-checks and saves
      draft_v2

All decisions are recorded in audit_logs.
"""

from __future__ import annotations

import time

from sqlalchemy.orm import Session

from app.db.models.approval_model import Approval
from app.db.models.report_version_model import ReportVersion as ReportVersionModel
from app.db.models.ticket import Ticket
from app.event.safety import draft_safety_check
from app.orchestration.draft import LLMDraftReviser
from app.orchestration.state import ticket_to_state
from app.report.versioning import freeze_final_version, save_report_version
from app.audit.logger import write_audit_log
from app.review.errors import ReviewError, raise_review_error
from app.schemas.common import ApprovalStatus, ReportVersionTag, TicketStatus, WorkflowStep
from app.schemas.report import DraftReport
from app.schemas.review import ApproveRequest, RejectRequest, ReviseRequest, SystemReviseRequest
from app.workflow.state import stage_for_status

def _find_pending_approval(db: Session, ticket_id: int) -> Approval | None:
    """run_policy_aggregation_step에서 ROUTE_TO_HITL 시 생성한 pending
    Approval row를 찾는다. handle_approve/handle_reject가 새 row를 매번
    insert하는 대신 이 row를 update하도록 하기 위함."""
    return (
        db.query(Approval)
        .filter(Approval.ticket_id == ticket_id, Approval.status == ApprovalStatus.PENDING.value)
        .order_by(Approval.id.desc())
        .first()
    )
    
def _find_latest_approval(db: Session, ticket_id: int) -> Approval | None:
    """티켓의 가장 최근 Approval row를 상태 무관하게 찾는다.
    (아직 사용처 없음 -- revise 시 pending 리셋 여부는 팀 논의 중)"""
    return (
        db.query(Approval)
        .filter(Approval.ticket_id == ticket_id)
        .order_by(Approval.id.desc())
        .first()
    )

def handle_approve(
    db: Session,
    ticket: Ticket,
    public_ticket_id: str,
    request: ApproveRequest,
    source_version: ReportVersionModel,
) -> dict:
    """
    약사 승인 처리.

    처리 내용:
        1. approvals 테이블에 승인 기록 저장
        2. source_version(최신 draft_v1 또는 draft_v2)을 그대로 freeze해
           final_v1으로 저장 -- 여기서 LLM을 다시 호출하지 않는다
        3. ticket.status/workflow_stage를 APPROVED로 전환
        4. audit log 기록

    Args:
        db: DB 세션
        ticket: 승인할 티켓
        request: 승인 요청 (reviewer, comment)
        source_version: 승인 대상이 된 최신 report_versions 레코드

    Returns:
        dict: 승인 결과

    예시 응답:
        {
            "ticket_id": "T-001",
            "approval_status": "approved",
            "final_report_version": "final_v1"
        }
    """
    start = time.time()

    # 1. 기존 pending 기록을 찾아 승인으로 갱신 (없으면 새로 생성 -- 레거시 데이터 대비)
    approval = _find_pending_approval(db, ticket.id)
    if approval is not None:
        approval.reviewer = request.reviewer
        approval.status = ApprovalStatus.APPROVED.value
        approval.comment = request.comment
    else:
        approval = Approval(
            ticket_id=ticket.id,
            reviewer=request.reviewer,
            status=ApprovalStatus.APPROVED.value,
            comment=request.comment,
        )
        db.add(approval)
    db.flush()

    # 2. final_v1 저장 -- source_version을 그대로 freeze (재생성 없음)
    freeze_final_version(
        db=db,
        ticket_id=ticket.id,
        source_version=source_version,
        approved_by=request.reviewer,
        approval_comment=request.comment,
    )

    # 3. 티켓 상태를 승인 완료로 전환
    ticket.status = TicketStatus.APPROVED.value
    ticket.workflow_stage = stage_for_status(TicketStatus.APPROVED).value

    # 4. audit log 기록
    duration_ms = int((time.time() - start) * 1000)
    write_audit_log(
        db=db,
        ticket_id=ticket.id,
        step_name=WorkflowStep.APPROVAL_DECISION,
        input_json={"reviewer": request.reviewer, "decision": "approve", "source_version": source_version.version_tag},
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
    ticket: Ticket,
    public_ticket_id: str,
    request: RejectRequest,
) -> dict:
    """
    약사 반려 처리.

    처리 내용:
        1. approvals 테이블에 반려 기록 저장
        2. ticket.status/workflow_stage를 REJECTED로 전환
        3. audit log 기록

    Args:
        db: DB 세션
        ticket: 반려할 티켓
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
    start = time.time()

    approval = _find_pending_approval(db, ticket.id)
    if approval is not None:
        approval.reviewer = request.reviewer
        approval.status = ApprovalStatus.REJECTED.value
        approval.comment = request.comment
    else:
        approval = Approval(
            ticket_id=ticket.id,
            reviewer=request.reviewer,
            status=ApprovalStatus.REJECTED.value,
            comment=request.comment,
        )
        db.add(approval)
    db.flush()

    # 2. 티켓 상태를 반려로 전환
    ticket.status = TicketStatus.REJECTED.value
    ticket.workflow_stage = stage_for_status(TicketStatus.REJECTED).value

    # 3. audit log 기록
    duration_ms = int((time.time() - start) * 1000)
    write_audit_log(
        db=db,
        ticket_id=ticket.id,
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
    ticket: Ticket,
    public_ticket_id: str,
    request: ReviseRequest,
) -> dict:
    """
    약사가 직접 수정한 초안 처리 (LLM 호출 없음).

    처리 내용:
        1. 수정된 초안을 safety check 재실행
        2. 통과하면 draft_v2로 저장 (변경 사유/리뷰어 코멘트/safety 결과 포함)
        3. 차단 문장 있으면 action_review payload 재구성 필요
        4. audit log 기록

    Args:
        db: DB 세션
        ticket_id: 수정 요청 티켓 ID
        request: 수정 요청 (reviewer, revised_draft, 선택적 comment)

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
    start = time.time()

    # 1. safety check 재실행
    safety_result = draft_safety_check(request.revised_draft)

    new_version = None

    if not safety_result.needs_action_review:
        # 2. 안전하면 draft_v2 저장 -- 약사가 직접 수정했으므로 change_summary는
        # 고정 문구를 쓰고, change_reason/reviewer_comment는 약사가 준 comment를 사용.
        save_report_version(
            db=db,
            ticket_id=ticket.id,
            version_tag=ReportVersionTag.DRAFT_V2,
            content=request.revised_draft,
            created_by=request.reviewer,
            change_summary="Pharmacist edited the draft directly.",
            change_reason=request.comment,
            reviewer_comment=request.comment,
            safety_check_result=safety_result,
        )
        new_version = ReportVersionTag.DRAFT_V2.value
        ticket.status = TicketStatus.REVIEW_ROUTED.value
        ticket.workflow_stage = stage_for_status(TicketStatus.REVIEW_ROUTED).value
        
        existing_approval = _find_latest_approval(db, ticket.id)
        if existing_approval is not None:
            existing_approval.status = ApprovalStatus.PENDING.value
            existing_approval.reviewer = ""
            existing_approval.comment = None

    # 3. audit log 기록
    duration_ms = int((time.time() - start) * 1000)
    write_audit_log(
        db=db,
        ticket_id=ticket.id,
        step_name=WorkflowStep.APPROVAL_DECISION,
        input_json={
            "reviewer": request.reviewer,
            "decision": "revise",
            "revised_draft": request.revised_draft,
            "comment": request.comment,
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


def handle_system_revise(
    db: Session,
    ticket: Ticket,
    public_ticket_id: str,
    request: SystemReviseRequest,
    latest_version: ReportVersionModel,
    reviser: object | None = None,
) -> dict:
    """
    시스템이 약사의 의견(reviewer_comment)이나 이전 safety check에서 걸린
    blocked_sentences를 반영해 최신 구조화 draft를 제한적으로(bounded) 수정.

    "약사가 직접 수정"하는 handle_revise와 달리, 여기서는 LLMDraftReviser로
    revise_draft_prompt를 호출한다. 전체 재작성이 아니라, 문제로 지목된
    부분만 바꾸고 나머지 구조/문구는 최대한 보존하는 것이 목표다.

    처리 내용:
        1. latest_version.report_json을 DraftReport로 파싱 (없으면 에러)
        2. LLMDraftReviser로 제한적 수정 수행
        3. 수정된 결과에 safety check 재실행
        4. 통과하면 draft_v2로 저장 (change_summary/change_reason/reviewer_comment/safety 결과 포함)
        5. audit log 기록

    Args:
        db: DB 세션
        ticket: 수정 대상 티켓
        request: 시스템 수정 요청 (reviewer, reviewer_comment)
        latest_version: 최신 report_versions 레코드 (구조화 report_json 필요)

    Returns:
        dict: 수정 처리 결과 (handle_revise와 동일한 응답 shape)
    """
    start = time.time()

    if not latest_version.report_json:
        raise_review_error(
            ReviewError.NO_STRUCTURED_REPORT,
            {"ticket_id": public_ticket_id, "version_tag": latest_version.version_tag},
        )

    previous_report = DraftReport(**latest_version.report_json)
    state = ticket_to_state(db, ticket)
    blocked_sentences = []
    if ticket.safety_result:
        blocked_sentences = [
            item.get("original", "") for item in ticket.safety_result.get("blocked_sentences", [])
        ]

    reviser = reviser or LLMDraftReviser()
    revised_report, change_summary, change_reason = reviser.revise(
        state=state,
        previous_report=previous_report,
        reviewer_comment=request.reviewer_comment,
        blocked_sentences=blocked_sentences,
        evidence_result=state.evidence_result,
    )

    safety_result = draft_safety_check(revised_report.to_display_text())
    new_version = None

    if not safety_result.needs_action_review:
        save_report_version(
            db=db,
            ticket_id=ticket.id,
            version_tag=ReportVersionTag.DRAFT_V2,
            report=revised_report,
            created_by="system",
            change_summary=change_summary,
            change_reason=change_reason,
            reviewer_comment=request.reviewer_comment,
            safety_check_result=safety_result,
        )
        new_version = ReportVersionTag.DRAFT_V2.value
        
        ticket.status = TicketStatus.REVIEW_ROUTED.value
        ticket.workflow_stage = stage_for_status(TicketStatus.REVIEW_ROUTED).value
        
        existing_approval = _find_latest_approval(db, ticket.id)
        if existing_approval is not None:
            existing_approval.status = ApprovalStatus.PENDING.value
            existing_approval.reviewer = ""
            existing_approval.comment = None

    duration_ms = int((time.time() - start) * 1000)
    write_audit_log(
        db=db,
        ticket_id=ticket.id,
        step_name=WorkflowStep.APPROVAL_DECISION,
        input_json={
            "reviewer": request.reviewer,
            "decision": "system_revise",
            "reviewer_comment": request.reviewer_comment,
            "blocked_sentences": blocked_sentences,
        },
        output_json={
            "safety_check_passed": not safety_result.needs_action_review,
            "blocked_sentences": [b.model_dump() for b in safety_result.blocked_sentences],
            "new_version": new_version,
            "change_summary": change_summary,
            "change_reason": change_reason,
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
