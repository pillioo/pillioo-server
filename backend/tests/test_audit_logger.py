from __future__ import annotations

from datetime import datetime, timedelta

import pytest
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


from app.audit.logger import get_audit_trace, write_audit_log
from app.db.base import Base
from app.db.models.ticket import Ticket
from app.schemas.common import WorkflowStep


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


def make_ticket(db_session, **overrides) -> Ticket:
    defaults = dict(
        ticket_id="T-AUDIT-001",
        status="CREATED",
        workflow_stage="PENDING_INVENTORY",
        event_type="recall",
        drug_name="midazolam",
        ndc="00641601441",
    )
    defaults.update(overrides)
    ticket = Ticket(**defaults)
    db_session.add(ticket)
    db_session.commit()
    db_session.refresh(ticket)
    return ticket


def test_get_audit_trace_orders_chronologically_not_by_insertion(db_session) -> None:
    """Regression test: get_audit_trace previously ordered by AuditLog.timestamp,
    a column that doesn't exist on the model (only created_at/updated_at via
    TimeStampedModel) -- every call raised AttributeError. Fixed to order by
    created_at. Rows are inserted in reverse chronological order here so the
    test can only pass if the query genuinely sorts by created_at rather than
    returning insertion/PK order by coincidence."""
    ticket = make_ticket(db_session)
    base = datetime(2026, 7, 11, 12, 0, 0)

    second_entry = write_audit_log(
        db=db_session,
        ticket_id=ticket.id,
        step_name=WorkflowStep.EVIDENCE_RETRIEVAL,
        input_json={},
        output_json={"step_status": "succeeded"},
        duration_ms=20,
    )
    second_entry.created_at = base + timedelta(seconds=10)

    first_entry = write_audit_log(
        db=db_session,
        ticket_id=ticket.id,
        step_name=WorkflowStep.INVENTORY_MATCH,
        input_json={},
        output_json={"step_status": "succeeded"},
        duration_ms=10,
    )
    first_entry.created_at = base

    db_session.commit()

    trace = get_audit_trace(db=db_session, ticket_id=ticket.id)

    assert [entry.step_name.value for entry in trace] == ["inventory_match", "evidence_retrieval"]


def test_get_audit_trace_derives_display_fields_for_succeeded_failed_skipped(db_session) -> None:
    ticket = make_ticket(db_session)

    write_audit_log(
        db=db_session,
        ticket_id=ticket.id,
        step_name=WorkflowStep.INVENTORY_MATCH,
        input_json={},
        output_json={"step_status": "succeeded"},
        duration_ms=10,
    )
    write_audit_log(
        db=db_session,
        ticket_id=ticket.id,
        step_name=WorkflowStep.SAFETY_CHECK,
        input_json={},
        output_json={"step_status": "failed", "error_message": "LLM timeout"},
        duration_ms=30,
    )
    write_audit_log(
        db=db_session,
        ticket_id=ticket.id,
        step_name=WorkflowStep.POLICY_AGGREGATION,
        input_json={},
        output_json={"step_status": "skipped", "reason": "ticket already closed"},
        duration_ms=0,
    )
    db_session.commit()

    trace = get_audit_trace(db=db_session, ticket_id=ticket.id)
    by_step = {entry.step_name.value: entry for entry in trace}

    succeeded = by_step["inventory_match"]
    assert succeeded.status == "succeeded"
    assert succeeded.severity == "info"
    assert succeeded.title == "Inventory Match"
    assert succeeded.message == "Inventory Match completed successfully."

    failed = by_step["safety_check"]
    assert failed.status == "failed"
    assert failed.severity == "error"
    assert failed.title == "Safety Check"
    assert failed.message == "Safety Check failed: LLM timeout"

    skipped = by_step["policy_aggregation"]
    assert skipped.status == "skipped"
    assert skipped.severity == "warning"
    assert skipped.title == "Policy Aggregation"
    assert skipped.message == "Policy Aggregation skipped: ticket already closed"


def test_get_audit_trace_defaults_to_succeeded_when_step_status_missing(db_session) -> None:
    """output_json written before step_status existed (or steps that never
    set it) must still resolve to a sane default instead of erroring."""
    ticket = make_ticket(db_session)

    write_audit_log(
        db=db_session,
        ticket_id=ticket.id,
        step_name=WorkflowStep.TICKET_CREATED,
        input_json={},
        output_json={},
        duration_ms=5,
    )
    db_session.commit()

    trace = get_audit_trace(db=db_session, ticket_id=ticket.id)

    assert trace[0].status == "succeeded"
    assert trace[0].severity == "info"
