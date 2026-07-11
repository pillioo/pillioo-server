from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.db.base import TimeStampedModel


class TicketEvidenceSnapshot(TimeStampedModel):
    __tablename__ = "ticket_evidence_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "ticket_id",
            "snapshot_version",
            "snapshot_type",
            name="uq_ticket_evidence_snapshots_ticket_version_type",
        ),
    )

    ticket_id = Column(
        ForeignKey("tickets.id"),
        nullable=False,
        index=True,
    )
    source_audit_log_id = Column(
        ForeignKey("audit_logs.id"),
        nullable=True,
        index=True,
    )

    snapshot_version = Column(Integer, nullable=False)
    snapshot_type = Column(String, nullable=False, default="workflow_evidence")
    created_workflow_step = Column(String, nullable=False)

    evidence_status = Column(String, nullable=True)
    coverage_score = Column(Float, nullable=True)
    citations_ready = Column(Boolean, nullable=True)
    target_profile = Column(String, nullable=True)

    selected_chunks = Column(JSONB, nullable=False, default=list)
    citations = Column(JSONB, nullable=False, default=list)
    sufficiency_result = Column(JSONB, nullable=False, default=dict)
    retrieval_trace = Column(JSONB, nullable=False, default=dict)
    retrieval_plan = Column(JSONB, nullable=False, default=dict)
    retrieval_context = Column(JSONB, nullable=False, default=dict)

    ticket = relationship(
        "Ticket",
        back_populates="evidence_snapshots",
    )
    source_audit_log = relationship("AuditLog")
