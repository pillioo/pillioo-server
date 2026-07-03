"""
P4 - Review Router

FastAPI router for pharmacist review workspace endpoints.

Endpoints:
    GET  /tickets/{ticket_id}/review     → review payload (pharmacist screen)
    GET  /approval/pending               → pending approval list
    POST /approval/{ticket_id}/approve   → approve ticket
    POST /approval/{ticket_id}/reject    → reject ticket
    POST /approval/{ticket_id}/revise    → request revision
    GET  /audit/{ticket_id}              → full audit trace
    GET  /reports/{ticket_id}/versions   → all report versions
    GET  /reports/{ticket_id}            → latest report version
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.audit.logger import get_audit_trace
from app.db.models.approval import Approval
from app.db.session import get_db
from app.report.versioning import get_latest_report, get_report_versions
from app.review.approval import handle_approve, handle_reject, handle_revise
from app.review.errors import ReviewError, raise_review_error
from app.schemas.common import ApprovalStatus
from app.schemas.review import ApproveRequest, RejectRequest, ReviseRequest

router = APIRouter(tags=["review"])


# ──────────────────────────────────────────────
# Review Workspace
# ──────────────────────────────────────────────

@router.get("/tickets/{ticket_id}/review")
async def get_review_payload(
    ticket_id: str,
    db: Session = Depends(get_db),
):
    """
    약사가 티켓 하나를 열었을 때 보는 전체 화면 데이터 반환.
    review_type에 맞는 payload 구성.

    TODO: Jimin Orchestrator 완성 후 실제 TicketState 조회로 교체
    """
    # TODO: 실제 TicketState 조회로 교체
    # state = get_ticket_state(db, ticket_id)
    # if not state:
    #     raise_review_error(ReviewError.TICKET_NOT_FOUND, {"ticket_id": ticket_id})
    # return build_review_payload(state)
    raise_review_error(
        ReviewError.REVIEW_NOT_FOUND,
        {"ticket_id": ticket_id, "reason": "Orchestrator connection pending"}
    )

@router.get("/approval/pending")
async def get_pending_approvals(
    db: Session = Depends(get_db),
):
    """
    승인 대기 중인 티켓 목록 반환.
    """
    pending = (
        db.query(Approval)
        .filter(Approval.status == ApprovalStatus.PENDING.value)
        .order_by(Approval.created_at.asc())
        .all()
    )

    return [
        {
            "ticket_id": a.ticket_id,
            "approval_status": a.status,
            "created_at": a.created_at,
        }
        for a in pending
    ]


# ──────────────────────────────────────────────
# Approval Actions
# ──────────────────────────────────────────────

@router.post("/approval/{ticket_id}/approve")
async def approve_ticket(
    ticket_id: str,
    request: ApproveRequest,
    db: Session = Depends(get_db),
):
    """
    약사 승인 처리.
    승인 기록 저장 + final_v1 보고서 버전 저장.
    한 티켓에 final_v1은 하나만 존재 가능.
    """
    # final_v1 중복 방지
    from app.db.models.report import ReportVersion as ReportVersionModel
    from app.schemas.common import ReportVersionTag

    existing_final = (
        db.query(ReportVersionModel)
        .filter(
            ReportVersionModel.ticket_id == ticket_id,
            ReportVersionModel.version_tag == ReportVersionTag.FINAL_V1.value,
        )
        .first()
    )

    if existing_final:
        raise_review_error(
            ReviewError.INVALID_VERSION_TAG,
            {"ticket_id": ticket_id, "reason": "final_v1 already exists for this ticket"},
        )

    # TODO: 실제 TicketState에서 draft_text 가져오도록 교체
    # state = get_ticket_state(db, ticket_id)
    # current_draft = state.draft_text
    # 현재는 최신 버전에서 가져오는 방식으로 대체
    latest = get_latest_report(db=db, ticket_id=ticket_id)
    if not latest:
        raise_review_error(
            ReviewError.REPORT_NOT_FOUND,
            {"ticket_id": ticket_id}
        )
    current_draft = latest.content

    return handle_approve(
        db=db,
        ticket_id=ticket_id,
        request=request,
        current_draft=current_draft,
    )


@router.post("/approval/{ticket_id}/reject")
async def reject_ticket(
    ticket_id: str,
    request: RejectRequest,
    db: Session = Depends(get_db),
):
    """
    약사 반려 처리.
    반려 사유 필수 입력.
    """
    return handle_reject(
        db=db,
        ticket_id=ticket_id,
        request=request,
    )


@router.post("/approval/{ticket_id}/revise")
async def revise_ticket(
    ticket_id: str,
    request: ReviseRequest,
    db: Session = Depends(get_db),
):
    """
    약사 수정 요청 처리.
    수정된 초안을 safety check 재실행 후 draft_v2 저장.
    재차단 문장 있으면 needs_action_review: True 반환.
    """
    return handle_revise(
        db=db,
        ticket_id=ticket_id,
        request=request,
    )


# ──────────────────────────────────────────────
# Audit & Report
# ──────────────────────────────────────────────

@router.get("/audit/{ticket_id}")
async def get_audit_log(
    ticket_id: str,
    db: Session = Depends(get_db),
):
    """
    특정 티켓의 전체 처리 기록 반환.
    "왜 이 티켓이 evidence_review로 갔는가" 추적 가능.
    """
    trace = get_audit_trace(db=db, ticket_id=ticket_id)

    if not trace:
        raise_review_error(
            ReviewError.TICKET_NOT_FOUND,
            {"ticket_id": ticket_id},
        )

    return trace


@router.get("/reports/{ticket_id}/versions")
async def get_report_version_list(
    ticket_id: str,
    db: Session = Depends(get_db),
):
    """
    특정 티켓의 모든 보고서 버전 목록 반환.
    draft_v1 → draft_v2 → final_v1 순서로 조회.
    """
    versions = get_report_versions(db=db, ticket_id=ticket_id)

    if not versions:
        raise_review_error(
            ReviewError.REPORT_NOT_FOUND,
            {"ticket_id": ticket_id},
        )

    return versions


@router.get("/reports/{ticket_id}")
async def get_latest_report_version(
    ticket_id: str,
    db: Session = Depends(get_db),
):
    """
    특정 티켓의 가장 최신 보고서 버전 반환.
    """
    version = get_latest_report(db=db, ticket_id=ticket_id)

    if not version:
        raise_review_error(
            ReviewError.REPORT_NOT_FOUND,
            {"ticket_id": ticket_id},
        )

    return version
