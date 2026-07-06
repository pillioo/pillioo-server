from sqlalchemy import Column, Enum, String, Text, ForeignKey
from sqlalchemy.orm import relationship

from app.db.base import TimeStampedModel


class Approval(TimeStampedModel):
    __tablename__ = "approvals"

    ticket_id = Column(
        ForeignKey("tickets.id"),
        nullable=False
    )

    reviewer = Column(
        String,
        nullable=False
    )

    status = Column(
        Enum(
            "approved",
            "rejected",
            "revised",
            name="approval_status"
        ),
        nullable=False
    )

    comment = Column(
        Text,
        nullable=True
    )

    ticket = relationship(
        "Ticket",
        back_populates="approvals"
    )