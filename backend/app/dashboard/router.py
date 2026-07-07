from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models.ticket import Ticket

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
def get_dashboard_summary(db: Session = Depends(get_db)):
    """
    전체 티켓 현황과 통계를 반환한다.
    """

    # 전체 티켓 수
    total_tickets = db.query(Ticket).count()

    # 최근 티켓 5개
    recent_tickets = db.query(Ticket).order_by(Ticket.created_at.desc()).limit(5).all()
    recent_list = [
        {
            "id": t.id,
            "title": t.title,
            "description": t.description,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in recent_tickets
    ]

    return {
        "total_tickets": total_tickets,
        "recent_tickets": recent_list,
    }