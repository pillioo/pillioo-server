from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


# JSONB has no sqlite compiler by default; map it to plain JSON so the real
# ORM models/tables can be created against an in-memory sqlite DB for these
# endpoint tests instead of requiring a live Postgres instance.
@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json_for_sqlite(element, compiler, **kw):
    return "JSON"


from app.db.base import Base
from app.db.session import get_db
import app.db.models.approval_model  # noqa: F401
import app.db.models.audit_log_model  # noqa: F401
import app.db.models.chat_model  # noqa: F401
import app.db.models.report_version_model  # noqa: F401
import app.db.models.ticket  # noqa: F401

from app.db.models.approval_model import Approval
from app.db.models.ticket import Ticket
from app.main import app
from app.schemas.common import ApprovalStatus


@pytest.fixture()
def client_and_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client, testing_session_local

    app.dependency_overrides.clear()


def _upload(client: TestClient, *, recall_number: str, drug_name: str) -> str:
    payload = {
        "recall_number": recall_number,
        "product_description": drug_name,
        "reason_for_recall": "Subpotent drug product",
        "classification": "class_i",
        "product_ndc": "00641-6014-41",
        "lot_number": "LOT-A",
        "recall_initiation_date": "2026-07-09",
        "status": "ongoing",
    }
    resp = client.post("/events/upload", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()["ticket_id"]


def test_list_tickets_returns_all_with_pagination_metadata(client_and_session) -> None:
    client, _ = client_and_session
    _upload(client, recall_number="D-LIST-001", drug_name="Midazolam HCl Injection")
    _upload(client, recall_number="D-LIST-002", drug_name="Amiodarone Hydrochloride")
    _upload(client, recall_number="D-LIST-003", drug_name="Dobutamine Injection")

    resp = client.get("/tickets")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["total"] == 3
    assert body["limit"] == 20
    assert body["offset"] == 0
    assert len(body["items"]) == 3
    # Newest first (created_at desc).
    assert body["items"][0]["recall_number"] == "D-LIST-003"


def test_list_tickets_filters_by_recall_number(client_and_session) -> None:
    client, _ = client_and_session
    _upload(client, recall_number="D-FILT-001", drug_name="Midazolam HCl Injection")
    _upload(client, recall_number="D-FILT-002", drug_name="Amiodarone Hydrochloride")

    resp = client.get("/tickets", params={"recall_number": "D-FILT-002"})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["total"] == 1
    assert body["items"][0]["recall_number"] == "D-FILT-002"


def test_list_tickets_free_text_search_matches_drug_name(client_and_session) -> None:
    client, _ = client_and_session
    _upload(client, recall_number="D-Q-001", drug_name="Midazolam HCl Injection")
    _upload(client, recall_number="D-Q-002", drug_name="Amiodarone Hydrochloride")

    resp = client.get("/tickets", params={"q": "midazolam"})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["total"] == 1
    # drug_name is normalized (lowercased) during event ingestion.
    assert "midazolam" in body["items"][0]["drug_name"].lower()


def test_list_tickets_filters_by_status(client_and_session) -> None:
    client, _ = client_and_session
    _upload(client, recall_number="D-STATUS-001", drug_name="Midazolam HCl Injection")

    matching = client.get("/tickets", params={"status": "CREATED"})
    assert matching.json()["total"] == 1

    non_matching = client.get("/tickets", params={"status": "APPROVED"})
    assert non_matching.json()["total"] == 0


def test_list_tickets_pagination_slices_results(client_and_session) -> None:
    client, _ = client_and_session
    for i in range(5):
        _upload(client, recall_number=f"D-PAGE-{i:03d}", drug_name="Midazolam HCl Injection")

    page1 = client.get("/tickets", params={"limit": 2, "offset": 0}).json()
    page2 = client.get("/tickets", params={"limit": 2, "offset": 2}).json()

    assert page1["total"] == 5
    assert page2["total"] == 5
    assert len(page1["items"]) == 2
    assert len(page2["items"]) == 2
    page1_ids = {item["ticket_id"] for item in page1["items"]}
    page2_ids = {item["ticket_id"] for item in page2["items"]}
    assert page1_ids.isdisjoint(page2_ids)


def test_approval_pending_returns_public_ticket_id_and_internal_id(client_and_session) -> None:
    """Regression test: /approval/pending previously returned the internal
    integer FK under the field name `ticket_id`, while every other endpoint
    in the same router uses `ticket_id` to mean the public string id. Now
    `ticket_id` is consistently the public string, and the internal FK is
    under `internal_id`."""
    client, session_local = client_and_session
    ticket_id = _upload(client, recall_number="D-PEND-001", drug_name="Midazolam HCl Injection")

    # No workflow path currently creates an Approval row with status=pending
    # (Approval rows are only written at approve/reject time, already
    # decided) -- inserted directly here to test this endpoint's
    # serialization/field-naming in isolation from that separate gap.
    db = session_local()
    try:
        ticket = db.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()
        internal_id = ticket.id
        approval = Approval(
            ticket_id=ticket.id,
            reviewer="pharm-1",
            status=ApprovalStatus.PENDING.value,
        )
        db.add(approval)
        db.commit()
    finally:
        db.close()

    resp = client.get("/approval/pending")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert len(body) == 1
    assert body[0]["ticket_id"] == ticket_id
    assert body[0]["internal_id"] == internal_id
    assert isinstance(body[0]["internal_id"], int)
