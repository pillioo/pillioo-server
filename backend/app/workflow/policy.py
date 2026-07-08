from __future__ import annotations

from app.schemas.common import Classification, EvidenceStatus, ReviewType
from app.schemas.evidence import SufficiencyCheckResult
from app.schemas.workflow import TicketState


MIN_EVIDENCE_COVERAGE_SCORE = 0.8


def requires_evidence_review(sufficiency: SufficiencyCheckResult | None) -> bool:
    # Be conservative: evidence can require review even when the coarse
    # status is not explicitly INSUFFICIENT.
    if sufficiency is None:
        return True
    if sufficiency.needs_evidence_review:
        return True
    if sufficiency.evidence_status != EvidenceStatus.SUFFICIENT:
        return True
    if getattr(sufficiency, "citations_ready", True) is False:
        return True
    if sufficiency.coverage_score < MIN_EVIDENCE_COVERAGE_SCORE:
        return True
    if sufficiency.missing_sources:
        return True
    if getattr(sufficiency, "weak_sources", []):
        return True
    return False


def can_auto_close_no_inventory_match(
    state: TicketState,
    *,
    allow_class_i_auto_close: bool = False,
) -> bool:
    # No inventory match is not always no impact; stale inventory or identity
    # drift should route to manual review, especially for high-risk recalls.
    inventory = state.inventory_result
    if inventory is None or inventory.matched:
        return False
    if inventory.needs_identity_review:
        return False
    if inventory.match_confidence != 0.0:
        return False
    if state.classification == Classification.CLASS_I and not allow_class_i_auto_close:
        return False
    if requires_evidence_review(state.sufficiency_check):
        return False
    return True


def manual_review_for_no_inventory_match(state: TicketState) -> ReviewType:
    if requires_evidence_review(state.sufficiency_check):
        return ReviewType.EVIDENCE_REVIEW
    return ReviewType.IDENTITY_REVIEW
