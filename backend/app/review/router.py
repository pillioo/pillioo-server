"""
Review Router

FastAPI router for pharmacist review workspace endpoints.

Endpoints:
    GET  /tickets/{ticket_id}            -> consolidated ticket detail (status, steps, can_rerun)
    GET  /tickets/{ticket_id}/review     -> review payload (pharmacist screen)
    GET  /approval/pending               -> pending approval list
    POST /approval/{ticket_id}/approve   -> approve ticket
    POST /approval/{ticket_id}/reject    -> reject ticket
    POST /approval/{ticket_id}/revise    -> request revision (pharmacist-edited draft)
    POST /approval/{ticket_id}/revise-with-llm -> request revision (system-revised draft)
    GET  /audit/{ticket_id}              -> full audit trace
    GET  /reports/{ticket_id}/versions   -> all report versions
    GET  /reports/{ticket_id}            -> latest report version
"""

from typing import Optional

from app.schemas.io import PendingApprovalItem, TicketListResponse
from app.schemas.report import ReportVersion
from app.schemas.workflow import AuditLogEntry
from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.audit.logger import get_audit_trace
from app.db.models.approval_model import Approval
from app.db.models.ticket import Ticket
from app.db.session import get_db
from app.report.versioning import get_latest_report, get_report_versions
from app.review.approval import handle_approve, handle_reject, handle_revise, handle_system_revise
from app.review.errors import ReviewError, raise_review_error
from app.review.tickets import get_ticket_by_public_id
from app.review.ticket_detail import build_ticket_detail
from app.schemas.common import ApprovalStatus, Priority, ReviewType
from app.schemas.io import TicketDetailResponse
from app.schemas.review import ApproveRequest, RejectRequest, ReviseRequest, SystemReviseRequest

from app.orchestration.state import ticket_to_state
from app.review.payload import build_review_payload
from app.schemas.common import TicketStatus

router = APIRouter(tags=["review"])


# ──────────────────────────────────────────────
# Review Workspace
# ──────────────────────────────────────────────

@router.get("/tickets", response_model=TicketListResponse)
async def list_tickets(
    status: Optional[TicketStatus] = None,
    review_type: Optional[ReviewType] = None,
    priority: Optional[Priority] = None,
    recall_number: Optional[str] = None,
    q: Optional[str] = Query(
        default=None,
        min_length=1,
        description="Free-text search over drug_name, recall_number, and ticket_id",
    ),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """
    대시보드/큐 화면용 티켓 목록 조회. status/review_type/priority/recall_number로
    필터링하고, q로 drug_name/recall_number/ticket_id 자유 검색, limit/offset으로
    페이지네이션한다. 최신순(created_at desc) 정렬.

    recall_number로 티켓 하나만 찾고 싶으면 `?recall_number=...`만 넘기면 됨
    (기존 단건 조회 엔드포인트를 대체 -- 이제 items 배열로 감싸서 반환).
    """
    query = db.query(Ticket)

    if status is not None:
        query = query.filter(Ticket.status == status.value)
    if review_type is not None:
        query = query.filter(Ticket.review_type == review_type.value)
    if priority is not None:
        query = query.filter(Ticket.priority == priority.value)
    if recall_number is not None:
        query = query.filter(Ticket.recall_number == recall_number)
    if q is not None:
        pattern = f"%{q}%"
        query = query.filter(
            or_(
                Ticket.drug_name.ilike(pattern),
                Ticket.recall_number.ilike(pattern),
                Ticket.ticket_id.ilike(pattern),
            )
        )

    total = query.count()
    tickets = (
        # id as a secondary sort key: created_at alone isn't a strict tiebreaker
        # (e.g. sqlite's CURRENT_TIMESTAMP has 1s resolution, so tickets created
        # within the same second would otherwise sort arbitrarily).
        query.order_by(Ticket.created_at.desc(), Ticket.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return TicketListResponse(
        items=[
            {
                "ticket_id": t.ticket_id,
                "status": t.status,
                "workflow_stage": t.workflow_stage,
                "drug_name": t.drug_name,
                "ndc": t.ndc,
                "lot": t.lot,
                "classification": t.classification,
                "recall_number": t.recall_number,
                "priority": t.priority,
                "review_type": t.review_type,
                "created_at": t.created_at,
                "updated_at": t.updated_at,
            }
            for t in tickets
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/tickets/{ticket_id}", response_model=TicketDetailResponse)
async def get_ticket_detail(
    ticket_id: str,
    db: Session = Depends(get_db),
):
    """
    워크플로우 실행 화면용 통합 조회.
    상태/단계별 진행 상황(audit_logs 기반)/실패 사유/재실행 가능 여부를 한 번에 반환한다.
    """
    ticket = get_ticket_by_public_id(db, ticket_id)
    return build_ticket_detail(db, ticket)


@router.get("/tickets/{ticket_id}/review")
async def get_review_payload(
    ticket_id: str,
    db: Session = Depends(get_db),
):
    """
    Returns the full review screen payload when a pharmacist opens a ticket.
    - Raises REVIEW_NOT_FOUND if ticket status is WORKFLOW_FAILED.
    - Raises REVIEW_NOT_FOUND if review_type is not yet determined.
    - Returns review payload if review_type is available.
    """
   
    ticket = get_ticket_by_public_id(db, ticket_id)


# Ticket is in a failed state — requires manual intervention before review
    if ticket.status == TicketStatus.WORKFLOW_FAILED.value:
        raise_review_error(
            ReviewError.REVIEW_NOT_FOUND,
            {
                "ticket_id": ticket_id,
                "reason": "Workflow failed — manual intervention required",
                "status": ticket.status,
            }
        )
    # Convert DB ticket to TicketState and build review payload
    state = ticket_to_state(db, ticket)

    if not state.review_type:
        raise_review_error(
            ReviewError.REVIEW_NOT_FOUND,
            {
                "ticket_id": ticket_id,
                "reason": "Review type not yet determined",
                "status": ticket.status,
            }
        )

    return build_review_payload(state)

@router.get("/approval/pending", response_model=list[PendingApprovalItem])
async def get_pending_approvals(
    db: Session = Depends(get_db),
):
    pending = (
        db.query(Approval)
        .join(Ticket, Approval.ticket_id == Ticket.id)
        .filter(Approval.status == ApprovalStatus.PENDING.value)
        .order_by(Approval.created_at.asc())
        .all()
    )

    return [
        {
            "ticket_id": a.ticket.ticket_id,
            "internal_id": a.ticket_id,
            "drug_name": a.ticket.drug_name,
            "recall_number": a.ticket.recall_number,
            "classification": a.ticket.classification,
            "review_type": a.ticket.review_type,
            "priority": a.ticket.priority,
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
    승인 기록 저장 + 최신 draft를 그대로 freeze한 final_v1 보고서 버전 저장.
    한 티켓에 final_v1은 하나만 존재 가능.
    """
    # final_v1 중복 방지
    from app.db.models.report_version_model import ReportVersion as ReportVersionModel
    from app.schemas.common import ReportVersionTag

    ticket = get_ticket_by_public_id(db, ticket_id)
    existing_final = (
        db.query(ReportVersionModel)
        .filter(
            ReportVersionModel.ticket_id == ticket.id,
            ReportVersionModel.version_tag == ReportVersionTag.FINAL_V1.value,
        )
        .first()
    )

    if existing_final:
        raise_review_error(
            ReviewError.INVALID_VERSION_TAG,
            {"ticket_id": ticket_id, "reason": "final_v1 already exists for this ticket"},
        )

    # Fetch latest draft version saved by Orchestrator (draft_v1 or draft_v2)
    latest = get_latest_report(db=db, ticket_id=ticket.id)
    if not latest:
        raise_review_error(
            ReviewError.REPORT_NOT_FOUND,
            {"ticket_id": ticket_id}
        )

    return handle_approve(
        db=db,
        ticket=ticket,
        public_ticket_id=ticket.ticket_id,
        request=request,
        source_version=latest,
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
    ticket = get_ticket_by_public_id(db, ticket_id)
    return handle_reject(
        db=db,
        ticket=ticket,
        public_ticket_id=ticket.ticket_id,
        request=request,
    )


@router.post("/approval/{ticket_id}/revise")
async def revise_ticket(
    ticket_id: str,
    request: ReviseRequest,
    db: Session = Depends(get_db),
):
    """
    약사가 직접 수정한 초안 처리 (LLM 호출 없음).
    수정된 초안을 safety check 재실행 후 draft_v2 저장.
    재차단 문장 있으면 needs_action_review: True 반환.
    """
    ticket = get_ticket_by_public_id(db, ticket_id)
    return handle_revise(
        db=db,
        ticket_id=ticket.id,
        public_ticket_id=ticket.ticket_id,
        request=request,
    )


@router.post("/approval/{ticket_id}/revise-with-llm")
async def revise_ticket_with_llm(
    ticket_id: str,
    request: SystemReviseRequest,
    db: Session = Depends(get_db),
):
    """
    시스템이 약사의 reviewer_comment를 반영해 최신 구조화 draft를 제한적으로
    수정 (revise_draft_prompt). 최신 report_versions 레코드에 구조화 본문
    (report_json)이 없으면 NO_STRUCTURED_REPORT 에러를 반환한다.
    수정 후 safety check 재실행 -> 통과 시 draft_v2 저장.
    """
    ticket = get_ticket_by_public_id(db, ticket_id)

    # Already-approved tickets are terminal (final_v1 is frozen and audited);
    # block any further system-driven revision instead of silently appending
    # another draft_v2 behind the pharmacist's back.
    if ticket.status == TicketStatus.APPROVED.value:
        raise_review_error(
            ReviewError.INVALID_VERSION_TAG,
            {"ticket_id": ticket_id, "reason": "Ticket already approved — cannot revise a finalized report"},
        )

    latest = get_latest_report(db=db, ticket_id=ticket.id)
    if not latest:
        raise_review_error(
            ReviewError.REPORT_NOT_FOUND,
            {"ticket_id": ticket_id}
        )

    return handle_system_revise(
        db=db,
        ticket=ticket,
        public_ticket_id=ticket.ticket_id,
        request=request,
        latest_version=latest,
    )


# ──────────────────────────────────────────────
# Audit & Report
# ──────────────────────────────────────────────

@router.get("/audit/{ticket_id}", response_model=list[AuditLogEntry])
async def get_audit_log(
    ticket_id: str,
    db: Session = Depends(get_db),
):
    """
    특정 티켓의 전체 처리 기록 반환.
    "왜 이 티켓이 evidence_review로 갔는가" 추적 가능.
    """
    ticket = get_ticket_by_public_id(db, ticket_id)
    trace = get_audit_trace(db=db, ticket_id=ticket.id)

    if not trace:
        raise_review_error(
            ReviewError.TICKET_NOT_FOUND,
            {"ticket_id": ticket_id},
        )

    return trace


@router.get("/reports/{ticket_id}/versions", response_model=list[ReportVersion])
async def get_report_version_list(
    ticket_id: str,
    db: Session = Depends(get_db),
):
    """
    특정 티켓의 모든 보고서 버전 목록 반환.
    draft_v1 → draft_v2 → final_v1 순서로 조회.
    """
    ticket = get_ticket_by_public_id(db, ticket_id)
    versions = get_report_versions(db=db, ticket_id=ticket.id)

    if not versions:
        raise_review_error(
            ReviewError.REPORT_NOT_FOUND,
            {"ticket_id": ticket_id},
        )

    return versions


@router.get("/reports/{ticket_id}", response_model=ReportVersion)
async def get_latest_report_version(
    ticket_id: str,
    db: Session = Depends(get_db),
):
    """
    특정 티켓의 가장 최신 보고서 버전 반환.
    """
    ticket = get_ticket_by_public_id(db, ticket_id)
    version = get_latest_report(db=db, ticket_id=ticket.id)

    if not version:
        raise_review_error(
            ReviewError.REPORT_NOT_FOUND,
            {"ticket_id": ticket_id},
        )

    return version
