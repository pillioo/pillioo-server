from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, cast, Date
from datetime import date

from app.db.session import get_db
from app.db.models.ticket import Ticket
from app.db.models.approval import Approval

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
def get_dashboard_summary(db: Session = Depends(get_db)):
    """
    전체 티켓 현황과 통계를 반환한다.
    """

    # 전체 티켓 수
    total_tickets = db.query(Ticket).count()

    # 상태별 분포
    by_status = {}
    status_counts = db.query(Ticket.status, func.count(Ticket.id)).group_by(Ticket.status).all()
    for status, count in status_counts:
        if status:
            by_status[str(status)] = count

    # review_type별 분포
    by_review_type = {}
    review_counts = db.query(Ticket.review_type, func.count(Ticket.id)).group_by(Ticket.review_type).all()
    for review_type, count in review_counts:
        if review_type:
            by_review_type[str(review_type)] = count

    # pending approvals 수
    try:
        pending_approvals = db.query(Approval).filter(
            Approval.status == "pending"
        ).count()
    except Exception:
        pending_approvals = 0

    # workflow failed 수
    workflow_failed = db.query(Ticket).filter(
        Ticket.status == "WORKFLOW_FAILED"
    ).count()

    # high priority 수
    high_priority = db.query(Ticket).filter(
        Ticket.priority == "HIGH"
    ).count()

    # 오늘 생성된 티켓 수
    today = date.today()
    today_created = db.query(Ticket).filter(
        cast(Ticket.created_at, Date) == today
    ).count()

    # evidence review 대기 수
    evidence_review_pending = db.query(Ticket).filter(
        Ticket.review_type == "evidence_review",
        Ticket.status == "REVIEW_ROUTED"
    ).count()

    # 긴급 티켓 목록 (urgent=True 또는 days_remaining <= 3)
    urgent_tickets_query = db.query(Ticket).filter(
        Ticket.status != "CLOSED"
    ).order_by(Ticket.created_at.desc()).limit(5).all()

    urgent_tickets = [
        {
            "ticket_id": t.ticket_id,
            "drug_name": t.drug_name,
            "status": str(t.status) if t.status else None,
            "review_type": str(t.review_type) if t.review_type else None,
            "priority": str(t.priority) if hasattr(t, "priority") else None,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in urgent_tickets_query
    ]

    # 최근 실패 사유
    failed_tickets = db.query(Ticket).filter(
        Ticket.status == "WORKFLOW_FAILED"
    ).order_by(Ticket.created_at.desc()).limit(3).all()

    recent_failures = [
        {
            "ticket_id": t.ticket_id,
            "drug_name": t.drug_name,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in failed_tickets
    ]

    # 최근 티켓 5개
    recent_tickets = db.query(Ticket).order_by(Ticket.created_at.desc()).limit(5).all()
    recent_list = [
        {
            "ticket_id": t.ticket_id,
            "drug_name": t.drug_name,
            "status": str(t.status) if t.status else None,
            "review_type": str(t.review_type) if t.review_type else None,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in recent_tickets
    ]

    return {
        "total_tickets": total_tickets,
        "by_status": by_status,
        "by_review_type": by_review_type,
        "pending_approvals": pending_approvals,
        "workflow_failed": workflow_failed,
        "high_priority": high_priority,
        "today_created": today_created,
        "evidence_review_pending": evidence_review_pending,
        "urgent_tickets": urgent_tickets,
        "recent_failures": recent_failures,
        "recent_tickets": recent_list,
    }