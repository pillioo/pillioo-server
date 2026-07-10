from sqlalchemy import Column, DateTime, String, Text, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
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

    # Structured report body (see app.schemas.report.DraftReport). Nullable
    # for backward compatibility with rows written before this column
    # existed; report_text remains the source of truth for plain-text
    # consumers (chat prompt context, draft_safety_check, etc.) regardless.
    report_json = Column(JSONB, nullable=True)

    # "workflow" for system-generated versions, or a pharmacist identifier.
    created_by = Column(String, nullable=True)

    # draft_v2 revision metadata -- only populated on revised versions.
    change_summary = Column(Text, nullable=True)
    change_reason = Column(Text, nullable=True)
    reviewer_comment = Column(Text, nullable=True)
    safety_check_result = Column(JSONB, nullable=True)

    # final_v1 approval metadata -- only populated on the frozen final version.
    approved_by = Column(String, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    approval_comment = Column(Text, nullable=True)
    source_version = Column(String, nullable=True)

    ticket = relationship(
        "Ticket",
        back_populates="report_versions"
    )
