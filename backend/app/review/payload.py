"""
P4 - Review Payload Builder

Constructs the pharmacist-facing review screen data
based on the review_type determined by the Orchestrator.

Each review type shows different information to guide the pharmacist's decision.
"""

from sqlalchemy.orm import Session

from app.schemas.common import ApprovalStatus, Department, ReviewType
from app.schemas.review import (
    ActionReviewPayload,
    EvidenceReviewPayload,
    FinalApprovalPayload,
    IdentityReviewPayload,
    ReviewPayload,
    TicketSummary,
    IdentityIssue,
    EvidenceIssue,
)
from app.schemas.workflow import TicketState
from backend.app.review.errors import ReviewError, ReviewError, raise_review_error


def build_review_payload(state: TicketState) -> ReviewPayload:
    """
    TicketState를 받아서 review_type에 맞는 약사 화면 데이터 구성.

    Orchestrator가 review_type 결정 후 호출.

    Args:
        state: 현재 티켓 전체 상태

    Returns:
        ReviewPayload: review_type별 payload
            - identity_review  → IdentityReviewPayload
            - evidence_review  → EvidenceReviewPayload
            - action_review    → ActionReviewPayload
            - final_approval   → FinalApprovalPayload

    Raises:
        ValueError: 지원하지 않는 review_type이 들어온 경우
    """
    review_type = state.review_type

    # 공통 summary 구성
    summary = TicketSummary(
        drug_name=state.event_normalized.drug_name if state.event_normalized else "",
        event_type=state.event_type,
        classification=state.classification,
        priority=state.priority,
    )

    if review_type == ReviewType.IDENTITY_REVIEW:
        # NDC/lot 매칭이 불확실한 경우
        # 약사가 직접 재고 확인 필요
        match_result = state.inventory_result
        impact = state.impact_summary

        return IdentityReviewPayload(
            ticket_id=state.ticket_id,
            approval_status=state.approval_status,
            summary=summary,
            identity_issue=IdentityIssue(
                input_ndc=match_result.ndc if match_result else "",
                matched_ndc=match_result.matched_ndc if match_result else None,
                match_confidence=match_result.confidence if match_result else 0.0,
                reason=match_result.match_reason if match_result else "",
            ),
            affected_departments=[
                Department(d) for d in (impact.affected_departments if impact else [])
            ],
            total_quantity=impact.total_quantity if impact else 0,
        )

    elif review_type == ReviewType.EVIDENCE_REVIEW:
        # 근거 문서가 부족한 경우
        # 약사에게 어떤 문서가 없는지 보여줌
        sufficiency = state.sufficiency_check
        evidence = state.evidence_result

        return EvidenceReviewPayload(
            ticket_id=state.ticket_id,
            approval_status=state.approval_status,
            summary=summary,
            evidence_issue=EvidenceIssue(
                required_sources=sufficiency.required_sources if sufficiency else [],
                found_sources=sufficiency.found_sources if sufficiency else [],
                missing_sources=sufficiency.missing_sources if sufficiency else [],
                coverage_score=sufficiency.coverage_score if sufficiency else 0.0,
            ),
            draft_text=state.draft_text or "",
            citations=state.draft_citations,
        )

    elif review_type == ReviewType.ACTION_REVIEW:
        # 위험 문장이 감지된 경우
        # 원문 문장과 수정된 초안을 나란히 보여줌
        safety = state.safety_result

        return ActionReviewPayload(
            ticket_id=state.ticket_id,
            approval_status=state.approval_status,
            summary=summary,
            blocked_sentences=safety.blocked_sentences if safety else [],
            original_draft=state.draft_text or "",
            revised_draft=safety.revised_draft if safety else "",
            citations=state.draft_citations,
        )

    elif review_type == ReviewType.FINAL_APPROVAL:
        # 모든 검사 통과 — 최종 승인 요청
        sufficiency = state.sufficiency_check
        inventory = state.inventory_result

        return FinalApprovalPayload(
            ticket_id=state.ticket_id,
            approval_status=state.approval_status,
            summary=summary,
            draft_text=state.draft_text or "",
            citations=state.draft_citations,
            evidence_coverage=sufficiency.coverage_score if sufficiency else 0.0,
            inventory_confidence=inventory.confidence if inventory else 0.0,
        )

    else:
        from app.review.errors import ReviewError, raise_review_error
        raise_review_error(
            ReviewError.INVALID_REVIEW_TYPE,
            {"review_type": str(review_type)}
        )
