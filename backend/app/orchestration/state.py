from __future__ import annotations

from datetime import datetime, timezone

from app.db.models.ticket import Ticket
from app.schemas.common import (
    ApprovalStatus,
    Classification,
    EventType,
    TicketStatus,
)
from app.schemas.event import EventNormalized, SafetyCheckResult
from app.schemas.evidence import DraftCitation, EvidenceResult, SufficiencyCheckResult
from app.schemas.inventory import ImpactSummary, InventoryMatchResult
from app.schemas.workflow import ReviewDecision, TicketState, TrustChecks


def ticket_to_state(ticket: Ticket) -> TicketState:
    event = EventNormalized(
        event_id=ticket.openfda_id or ticket.recall_number or ticket.ticket_id,
        event_type=EventType(ticket.event_type),
        drug_name=ticket.drug_name,
        ndc=ticket.ndc,
        lot=ticket.lot,
        classification=Classification(ticket.classification) if ticket.classification else None,
        status=ticket.source_status or "unknown",
        recall_number=ticket.recall_number,
        product_description=ticket.product_description,
        reason_for_recall=ticket.reason_for_recall,
    )

    now = datetime.now(timezone.utc)
    return TicketState(
        ticket_id=ticket.ticket_id,
        event_type=event.event_type,
        classification=event.classification,
        status=TicketStatus(ticket.status) if ticket.status in TicketStatus._value2member_map_ else TicketStatus.CREATED,
        event_normalized=event,
        inventory_result=_parse_optional(InventoryMatchResult, ticket.inventory_result),
        impact_summary=_parse_optional(ImpactSummary, ticket.impact_summary),
        evidence_result=_parse_optional(EvidenceResult, ticket.evidence_result),
        sufficiency_check=_parse_optional(SufficiencyCheckResult, ticket.sufficiency_check),
        draft_text=ticket.draft_text,
        draft_citations=[DraftCitation(**item) for item in ticket.draft_citations or []],
        safety_result=_parse_optional(SafetyCheckResult, ticket.safety_result),
        trust_checks=TrustChecks(**ticket.trust_checks) if ticket.trust_checks else TrustChecks(),
        policy_decision=_parse_optional(ReviewDecision, ticket.policy_decision),
        approval_status=ApprovalStatus.PENDING,
        created_at=ticket.created_at or now,
        updated_at=ticket.updated_at or ticket.created_at or now,
    )


def _parse_optional(schema, value):
    if not value:
        return None
    return schema(**value)
