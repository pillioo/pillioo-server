from __future__ import annotations

from app.schemas.common import EvidenceStatus, PolicyDecisionAction, ReviewType
from app.schemas.workflow import ReviewDecision, TicketState
from app.workflow.policy import (
    can_auto_close_no_inventory_match,
    manual_review_for_no_inventory_match,
    requires_evidence_review,
)


def aggregate_policy_decision(state: TicketState) -> ReviewDecision:
    inventory = state.inventory_result
    sufficiency = state.sufficiency_check
    safety = state.safety_result

    if inventory and not inventory.matched:
        if can_auto_close_no_inventory_match(state):
            return ReviewDecision(
                review_type=ReviewType.NO_IMPACT_CLOSE,
                reasons=["No matching inventory found and evidence supports no-impact closure."],
                decision=PolicyDecisionAction.CLOSE,
            )
        review_type = manual_review_for_no_inventory_match(state)
        return ReviewDecision(
            review_type=review_type,
            reasons=["No inventory match requires manual review before closure."],
            decision=PolicyDecisionAction.ROUTE_TO_HITL,
        )

    if inventory and inventory.needs_identity_review:
        return ReviewDecision(
            review_type=ReviewType.IDENTITY_REVIEW,
            reasons=[inventory.identity_review_reason or "Inventory identity requires review."],
            decision=PolicyDecisionAction.ROUTE_TO_HITL,
        )

    if requires_evidence_review(sufficiency):
        return ReviewDecision(
            review_type=ReviewType.EVIDENCE_REVIEW,
            reasons=["Required evidence is missing or weak."],
            decision=PolicyDecisionAction.ROUTE_TO_HITL,
        )

    if safety and safety.blocked_sentences:
        return ReviewDecision(
            review_type=ReviewType.ACTION_REVIEW,
            reasons=["Draft contains blocked action language."],
            decision=PolicyDecisionAction.ROUTE_TO_HITL,
        )

    if inventory and inventory.match_confidence < 0.5:
        return ReviewDecision(
            review_type=ReviewType.IDENTITY_REVIEW,
            reasons=["Inventory match confidence is below threshold."],
            decision=PolicyDecisionAction.ROUTE_TO_HITL,
        )

    return ReviewDecision(
        review_type=ReviewType.FINAL_APPROVAL,
        reasons=["Inventory, evidence, and safety checks passed."],
        decision=PolicyDecisionAction.REQUEST_FINAL_APPROVAL,
    )


def policy_audit_output(state: TicketState, decision: ReviewDecision, ticket_policy_decision: dict) -> dict:
    return {
        "step_status": "succeeded",
        "review_type": decision.review_type.value,
        "decision": decision.decision.value,
        "reasons": decision.reasons,
        "matched": state.inventory_result.matched if state.inventory_result else None,
        "match_confidence": state.inventory_result.match_confidence if state.inventory_result else None,
        "needs_identity_review": state.inventory_result.needs_identity_review if state.inventory_result else None,
        "evidence_status": state.sufficiency_check.evidence_status.value if state.sufficiency_check else None,
        "coverage_score": state.sufficiency_check.coverage_score if state.sufficiency_check else None,
        "missing_sources": [source.value for source in state.sufficiency_check.missing_sources] if state.sufficiency_check else [],
        "blocked_sentence_count": len(state.safety_result.blocked_sentences) if state.safety_result else 0,
        "final_routing_reason": decision.reasons[0] if decision.reasons else "",
        "policy_decision": ticket_policy_decision,
    }
