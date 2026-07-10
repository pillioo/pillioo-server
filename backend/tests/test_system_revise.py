from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker


# JSONB has no sqlite compiler by default; map it to plain JSON so the real
# ORM models can run against an in-memory sqlite DB instead of requiring a
# live Postgres instance.
@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json_for_sqlite(element, compiler, **kw):
    return "JSON"


from app.db.base import Base
from app.db.models.report_version_model import ReportVersion
from app.db.models.ticket import Ticket
from app.review.approval import handle_system_revise
from app.schemas.common import ReportVersionTag
from app.schemas.report import AffectedProduct, DraftReport, EvidenceSummary, InventoryImpact
from app.schemas.review import SystemReviseRequest


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def make_report(**overrides) -> DraftReport:
    defaults = dict(
        title="Midazolam recall review draft",
        summary="Midazolam class I recall notice. Quarantine affected lots pending pharmacist review.",
        affected_product=AffectedProduct(drug_name="midazolam", ndc="00641601441", lot="LOT-A"),
        inventory_impact=InventoryImpact(matched=True, affected_departments=["ICU"], total_quantity=5),
        evidence_summary=EvidenceSummary(coverage_score=0.9, found_sources=["sop"]),
        recommended_review_action="Pharmacist review required before further action.",
    )
    defaults.update(overrides)
    return DraftReport(**defaults)


class FakeReviser:
    """Stands in for LLMDraftReviser -- injected via handle_system_revise's
    `reviser` parameter so this test never touches a real LLM client."""

    def __init__(self, revised_report, change_summary="System-revised.", change_reason="reviewer feedback"):
        self.revised_report = revised_report
        self.change_summary = change_summary
        self.change_reason = change_reason
        self.calls: list[dict] = []

    def revise(self, **kwargs):
        self.calls.append(kwargs)
        return self.revised_report, self.change_summary, self.change_reason


def make_ticket(db_session, **overrides) -> Ticket:
    defaults = dict(
        ticket_id="T-SYS-REVISE-001",
        status="REVIEW_ROUTED",
        workflow_stage="PENDING_REVIEW",
        event_type="recall",
        drug_name="midazolam",
        ndc="00641601441",
        lot="LOT-A",
        classification="class_i",
        recall_number="D-SYS-001",
        recall_number_is_fallback=False,
        reason_for_recall="Subpotent drug product",
        product_description="Midazolam HCl Injection 1 mg/mL vial",
        source_status="ongoing",
        evidence_result={"top_chunks": [], "citations": []},
        safety_result={
            "blocked_sentences": [
                {
                    "original": "Discard the affected lots immediately.",
                    "category": "disposal_instruction",
                    "replaced_with": "Please consult the pharmacist before taking action.",
                }
            ],
            "revised_draft": "...",
            "needs_action_review": True,
        },
    )
    defaults.update(overrides)
    ticket = Ticket(**defaults)
    db_session.add(ticket)
    db_session.commit()
    db_session.refresh(ticket)
    return ticket


def _latest_draft_v2(db_session, ticket_id: int) -> ReportVersion | None:
    return (
        db_session.query(ReportVersion)
        .filter(ReportVersion.ticket_id == ticket_id, ReportVersion.version_tag == ReportVersionTag.DRAFT_V2.value)
        .first()
    )


def test_handle_system_revise_applies_bounded_edit_and_saves_draft_v2(db_session) -> None:
    ticket = make_ticket(db_session)
    previous_report = make_report()
    latest_version = ReportVersion(
        ticket_id=ticket.id,
        version_tag=ReportVersionTag.DRAFT_V1.value,
        report_text=previous_report.to_display_text(),
        report_json=previous_report.model_dump(mode="json"),
    )
    db_session.add(latest_version)
    db_session.commit()

    revised_report = previous_report.model_copy(
        update={"summary": "Revised: Pharmacist review required. Quarantine affected lots."}
    )
    fake_reviser = FakeReviser(revised_report)

    result = handle_system_revise(
        db=db_session,
        ticket=ticket,
        public_ticket_id=ticket.ticket_id,
        request=SystemReviseRequest(reviewer="pharm-1", reviewer_comment="please remove the disposal instruction"),
        latest_version=latest_version,
        reviser=fake_reviser,
    )

    assert result["new_version"] == "draft_v2"
    assert result["safety_check_passed"] is True

    # The blocked sentence from the ticket's prior safety_result must be
    # surfaced to the reviser so it knows what to fix.
    call = fake_reviser.calls[0]
    assert "Discard the affected lots immediately." in call["blocked_sentences"]
    assert call["reviewer_comment"] == "please remove the disposal instruction"

    saved = _latest_draft_v2(db_session, ticket.id)
    assert saved is not None
    assert saved.change_summary == "System-revised."
    assert saved.change_reason == "reviewer feedback"
    assert saved.reviewer_comment == "please remove the disposal instruction"
    assert saved.created_by == "system"
    assert saved.report_json["summary"] == revised_report.summary


def test_handle_system_revise_blocks_when_revised_report_still_unsafe(db_session) -> None:
    ticket = make_ticket(db_session)
    previous_report = make_report()
    latest_version = ReportVersion(
        ticket_id=ticket.id,
        version_tag=ReportVersionTag.DRAFT_V1.value,
        report_text=previous_report.to_display_text(),
        report_json=previous_report.model_dump(mode="json"),
    )
    db_session.add(latest_version)
    db_session.commit()

    # Reviser "fails" to remove the unsafe phrasing -- the safety re-check
    # after revision must still catch it, and draft_v2 must not be saved.
    still_unsafe_report = previous_report.model_copy(
        update={"recommended_review_action": "Discard the affected lots immediately."}
    )
    fake_reviser = FakeReviser(still_unsafe_report)

    result = handle_system_revise(
        db=db_session,
        ticket=ticket,
        public_ticket_id=ticket.ticket_id,
        request=SystemReviseRequest(reviewer="pharm-1", reviewer_comment="please simplify"),
        latest_version=latest_version,
        reviser=fake_reviser,
    )

    assert result["new_version"] is None
    assert result["safety_check_passed"] is False
    assert result["blocked_sentences"]
    assert _latest_draft_v2(db_session, ticket.id) is None


def test_handle_system_revise_errors_without_structured_report(db_session) -> None:
    ticket = make_ticket(db_session)
    latest_version = ReportVersion(
        ticket_id=ticket.id,
        version_tag=ReportVersionTag.DRAFT_V1.value,
        report_text="plain text only, no structured body",
        report_json=None,
    )
    db_session.add(latest_version)
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        handle_system_revise(
            db=db_session,
            ticket=ticket,
            public_ticket_id=ticket.ticket_id,
            request=SystemReviseRequest(reviewer="pharm-1", reviewer_comment="please fix"),
            latest_version=latest_version,
            reviser=FakeReviser(make_report()),
        )

    assert exc_info.value.detail["error_code"] == "NO_STRUCTURED_REPORT"
