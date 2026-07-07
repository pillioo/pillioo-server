from sqlalchemy import Column, String, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.db.base import TimeStampedModel


class AuditLog(TimeStampedModel):
    __tablename__ = "audit_logs"

    ticket_id = Column(
        ForeignKey("tickets.id"),
        nullable=False
    )

    step_name = Column(
        String,
        nullable=False
    )

    input_json = Column(
        JSONB,
        nullable=True
    )

    output_json = Column(
        JSONB,
        nullable=True
    )

    duration_ms = Column(
        Integer,
        nullable=True
    )

    ticket = relationship(
        "Ticket",
        back_populates="audit_logs"
    )