from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.db.models.ticket import Ticket
from app.schemas.common import TicketStatus
from app.schemas.event import EventNormalized
from app.workflow.state import stage_for_status


def get_or_create_ticket_record(db: Session, event: EventNormalized) -> tuple[Ticket, bool]:
    existing = find_existing_ticket(db, event)
    if existing is not None:
        return existing, False

    ticket = Ticket(
        ticket_id=f"T-{uuid.uuid4().hex.upper()}",
        status=TicketStatus.CREATED.value,
        workflow_stage=stage_for_status(TicketStatus.CREATED).value,
        priority=None,
        event_type=event.event_type.value,
        drug_name=event.drug_name,
        ndc=event.ndc,
        lot=event.lot,
        classification=event.classification.value if event.classification else None,
        recall_number=event.recall_number,
        recall_number_is_fallback=event.recall_number_is_fallback,
        reason_for_recall=event.reason_for_recall,
        product_description=event.product_description,
        openfda_id=event.event_id,
        source_status=event.status,
    )
    db.add(ticket)
    db.flush()
    db.refresh(ticket)
    return ticket, True


def create_ticket_record(db: Session, event: EventNormalized) -> Ticket:
    ticket, _ = get_or_create_ticket_record(db, event)
    return ticket


def find_existing_ticket(db: Session, event: EventNormalized) -> Ticket | None:
    # Service-level idempotency for MVP. Add a DB-level event_idempotency_key
    # unique constraint once the event identity contract is finalized.
    existing = (
        db.query(Ticket)
        .filter(
            Ticket.event_type == event.event_type.value,
            Ticket.openfda_id == event.event_id,
        )
        .first()
    )
    
    if not event.recall_number:
        return None
    filters = [
        Ticket.event_type == event.event_type.value,
        Ticket.recall_number == event.recall_number,
    ]
    if event.ndc:
        filters.append(Ticket.ndc == event.ndc)
    if event.lot:
        filters.append(Ticket.lot == event.lot)
    return db.query(Ticket).filter(*filters).first()


def build_event_idempotency_key(event: EventNormalized) -> str:
    parts = [
        event.event_type.value,
        event.event_id,
        event.recall_number,
        event.ndc or "",
        event.lot or "",
    ]
    return "|".join(part for part in parts if part)
