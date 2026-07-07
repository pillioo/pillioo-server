from sqlalchemy import Column, String, Text, ForeignKey
from sqlalchemy.orm import relationship

from app.db.base import TimeStampedModel


class ReportVersion(TimeStampedModel):
    __tablename__ = "report_versions"

    ticket_id = Column(
        ForeignKey("tickets.id"),
        nullable=False
    )

    version_tag = Column(
        String,
        nullable=False
    )
    # draft_v1
    # draft_v2
    # final_v1

    report_text = Column(
        Text,
        nullable=False
    )

    ticket = relationship(
        "Ticket",
        back_populates="report_versions"
    )