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

    # pending means a reviewer is assigned but has not decided yet.
    # Pre-assignment review waiting state belongs to tickets.workflow_stage/status.
    status = Column(
        Enum(
            "pending",
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
