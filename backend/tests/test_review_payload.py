from __future__ import annotations

from datetime import datetime, timezone

from app.review.payload import build_review_payload
from app.schemas.common import (
    ApprovalStatus,
    Classification,
    Department,
    EventType,
    MatchType,
    PolicyDecisionAction,
    Priority,
    ReviewType,
    TicketStatus,
)
from app.schemas.event import EventNormalized
from app.schemas.inventory import ImpactSummary, InventoryMatchResult
from app.schemas.workflow import ReviewDecision, TicketState


def test_identity_review_payload_uses_ticket_event_and_inventory_fields() -> None:
    now = datetime.now(timezone.utc)
    state = TicketState(
        ticket_id="T-IDENTITY",
        event_type=EventType.RECALL,
        classification=Classification.CLASS_I,
        status=TicketStatus.REVIEW_ROUTED,
        approval_status=ApprovalStatus.PENDING,
        event_normalized=EventNormalized(
            event_id="D-123-2026",
            event_type=EventType.RECALL,
            drug_name="Midazolam",
            ndc="00641601441",
            classification=Classification.CLASS_I,
            status="ongoing",
        ),
        inventory_result=InventoryMatchResult(
            matched=True,
            match_type=MatchType.FUZZY_NAME_MATCH,
            match_confidence=0.6,
            matched_rows=[
                {
                    "inventory_id": "INV-001",
                    "drug_name": "midazolam",
                    "ndc": "00641601442",
                    "quantity": 3,
                    "department": Department.ICU,
                    "days_remaining": 2,
                }
            ],
            needs_identity_review=True,
            identity_review_reason="Low confidence fuzzy match.",
        ),
        impact_summary=ImpactSummary(
            affected_departments=[Department.ICU],
            department_breakdown={Department.ICU: 3},
            total_quantity=3,
            priority=Priority.HIGH,
        ),
        policy_decision=ReviewDecision(
            review_type=ReviewType.IDENTITY_REVIEW,
            reasons=["Fuzzy match only."],
            decision=PolicyDecisionAction.ROUTE_TO_HITL,
        ),
        created_at=now,
        updated_at=now,
    )

    payload = build_review_payload(state)

    assert payload.identity_issue.input_ndc == "00641601441"
    assert payload.identity_issue.matched_ndc == "00641601442"
    assert payload.identity_issue.match_confidence == 0.6
    assert payload.identity_issue.reason == "Low confidence fuzzy match."
