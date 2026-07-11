from sqlalchemy import Boolean, Column, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.db.base import TimeStampedModel


class Ticket(TimeStampedModel):
    __tablename__ = "tickets"

    # 1. 시스템 내부 티켓 식별자 및 상태
    ticket_id = Column(String, unique=True, index=True, nullable=False)
    status = Column(String, nullable=False, default="CREATED")
    workflow_stage = Column(String, nullable=False, default="PENDING_INVENTORY")
    # Ticket-level priority; inventory_result.priority/urgent are step-level outputs.
    priority = Column(String, nullable=True)

    # 2. 약품 및 이벤트 기본 정보
    event_type = Column(String, nullable=False)
    drug_name = Column(String, nullable=False)
    ndc = Column(String, nullable=False, index=True)
    lot = Column(String, nullable=True)
    classification = Column(String, nullable=True)

    # 3. RAG/Evidence 및 외부 연동 데이터
    recall_number = Column(String, nullable=True)
    # recall_number이 event_id로 대체된 fallback 값인지 여부.
    # 워크플로우 재실행 시 recall_number을 강한 필터로 쓸지 판단하는 데 필요.
    recall_number_is_fallback = Column(Boolean, nullable=False, default=False, server_default="false")
    reason_for_recall = Column(String, nullable=True)
    product_description = Column(String, nullable=True)

    # 4. 중복 및 상태 변경 감지(Diff Detector)용 핵심 데이터
    openfda_id = Column(String, unique=True, index=True, nullable=True)
    source_status = Column(String, nullable=True)

    # 5. Orchestrator가 채워나가는 워크플로우 단계별 결과 (TicketState 영속화)
    inventory_result = Column(JSONB, nullable=True)
    impact_summary = Column(JSONB, nullable=True)
    evidence_result = Column(JSONB, nullable=True)
    sufficiency_check = Column(JSONB, nullable=True)
    draft_text = Column(Text, nullable=True)
    draft_citations = Column(JSONB, nullable=True)
    safety_result = Column(JSONB, nullable=True)
    trust_checks = Column(JSONB, nullable=True)
    policy_decision = Column(JSONB, nullable=True)
    review_type = Column(String, nullable=True)

    # P4 Relationships
    approvals = relationship(
        "Approval",
        back_populates="ticket"
    )

    audit_logs = relationship(
        "AuditLog",
        back_populates="ticket"
    )

    report_versions = relationship(
        "ReportVersion",
        back_populates="ticket"
    )

    evidence_snapshots = relationship(
        "TicketEvidenceSnapshot",
        back_populates="ticket"
    )
