from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models.ticket import Ticket
from app.review.errors import ReviewError, raise_review_error


def get_ticket_by_public_id(db: Session, ticket_id: str) -> Ticket:
    ticket = db.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()
    if ticket is None:
        raise_review_error(ReviewError.TICKET_NOT_FOUND, {"ticket_id": ticket_id})
    return ticket
