from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db.session import get_db
from app.models.ticket import Ticket

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
def get_dashboard_summary(db: Session = Depends(get_db)):
    """
    전체 티켓 현황과 통계를 반환한다.
    데모에서 시스템이 실제 서비스처럼 보이게 하는 엔드포인트.
    """

    # 전체 티켓 수
    total_tickets = db.query(Ticket).count()

    # 상태별 분포
    by_status = {}
    status_counts = db.query(Ticket.status, func.count(Ticket.id)).group_by(Ticket.status).all()
    for status, count in status_counts:
        by_status[str(status)] = count

    # review_type별 분포
    by_review_type = {}
    review_counts = db.query(Ticket.review_type, func.count(Ticket.id)).group_by(Ticket.review_type).all()
    for review_type, count in review_counts:
        if review_type:
            by_review_type[str(review_type)] = count

    # 최근 티켓 5개
    recent_tickets = db.query(Ticket).order_by(Ticket.created_at.desc()).limit(5).all()
    recent_list = [
        {
            "ticket_id": t.ticket_id,
            "drug_name": t.drug_name,
            "status": str(t.status),
            "review_type": str(t.review_type) if t.review_type else None,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in recent_tickets
    ]

    return {
        "total_tickets": total_tickets,
        "by_status": by_status,
        "by_review_type": by_review_type,
        "recent_tickets": recent_list,
    }