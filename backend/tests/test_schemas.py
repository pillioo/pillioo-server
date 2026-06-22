"""
Schema integration tests.

Validates that each schema enforces its invariants and that
cross-schema types compose correctly inside TicketState.
"""

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from app.schemas.common import (
    ApprovalStatus,
    BlockedCategory,
    Classification,
    Department,
    DocumentType,
    EvidenceStatus,
    EventType,
    MatchType,
    PolicyDecisionAction,
    Priority,
    ReviewType,
    TicketStatus,
    WorkflowStep,
)
from app.schemas.event import BlockedSentence, EventNormalized, SafetyCheckResult
from app.schemas.evidence import (
    Citation,
    DraftCitation,
    EvidenceChunk,
    EvidenceRoutingResult,
    EvidenceResult,
    SufficiencyCheckResult,
)
from app.schemas.io import ChatRequest, EvalResult, EventUploadResponse
from app.schemas.inventory import ImpactSummary, InventoryMatchResult, InventoryRow, TrustCheckResult
from app.schemas.review import IdentityIssue, IdentityReviewPayload, TicketSummary
from app.schemas.workflow import AuditLogEntry, ReviewDecision, TicketState, TrustChecks


# Fixtures

NOW = datetime(2026, 6, 20, 12, 0, 0)


def make_event_normalized(**overrides) -> EventNormalized:
    defaults = dict(
        event_id="EVT-001",
        event_type=EventType.RECALL,
        drug_name="Aspirin",
        ndc="12345678901",
        classification=Classification.CLASS_I,
        status="ongoing",
    )
    return EventNormalized(**{**defaults, **overrides})


def make_inventory_row(**overrides) -> InventoryRow:
    defaults = dict(
        inventory_id="INV-001",
        drug_name="aspirin",
        ndc="12345678901",
        quantity=100,
        department=Department.ICU,
        days_remaining=30,
    )
    return InventoryRow(**{**defaults, **overrides})


def make_inventory_match(**overrides) -> InventoryMatchResult:
    defaults = dict(
        matched=True,
        match_type=MatchType.EXACT_NDC_MATCH,
        match_confidence=0.99,
        matched_rows=[make_inventory_row()],
    )
    return InventoryMatchResult(**{**defaults, **overrides})


def make_impact_summary(**overrides) -> ImpactSummary:
    defaults = dict(
        affected_departments=[Department.ICU],
        department_breakdown={Department.ICU: 100},
        total_quantity=100,
        priority=Priority.HIGH,
    )
    return ImpactSummary(**{**defaults, **overrides})


def make_evidence_chunk(**overrides) -> EvidenceChunk:
    defaults = dict(
        content="Policy text here.",
        document_type=DocumentType.POLICY,
        section="2.1",
        similarity_score=0.95,
        source_path="/docs/policy.pdf",
        chunk_index=0,
        drug_name="aspirin",
    )
    return EvidenceChunk(**{**defaults, **overrides})


def make_evidence_result(**overrides) -> EvidenceResult:
    defaults = dict(
        top_chunks=[make_evidence_chunk()],
        citations=[Citation(source="/docs/policy.pdf", section="2.1", score=0.95)],
    )
    return EvidenceResult(**{**defaults, **overrides})


def make_sufficiency_check(**overrides) -> SufficiencyCheckResult:
    defaults = dict(
        required_sources=[DocumentType.POLICY, DocumentType.SOP],
        found_sources=[DocumentType.POLICY, DocumentType.SOP],
        missing_sources=[],
        coverage_score=1.0,
        evidence_status=EvidenceStatus.SUFFICIENT,
        needs_evidence_review=False,
    )
    return SufficiencyCheckResult(**{**defaults, **overrides})


def make_safety_check(**overrides) -> SafetyCheckResult:
    defaults = dict(
        blocked_sentences=[],
        revised_draft="Safe draft text.",
        needs_action_review=False,
    )
    return SafetyCheckResult(**{**defaults, **overrides})


def make_review_decision(**overrides) -> ReviewDecision:
    defaults = dict(
        review_type=ReviewType.FINAL_APPROVAL,
        reasons=["All checks passed."],
        decision=PolicyDecisionAction.REQUEST_FINAL_APPROVAL,
    )
    return ReviewDecision(**{**defaults, **overrides})


def make_ticket_state(**overrides) -> TicketState:
    defaults = dict(
        ticket_id="TICKET-001",
        event_type=EventType.RECALL,
        classification=Classification.CLASS_I,
        status=TicketStatus.APPROVED,
        event_normalized=make_event_normalized(),
        inventory_result=make_inventory_match(),
        impact_summary=make_impact_summary(),
        evidence_result=make_evidence_result(),
        sufficiency_check=make_sufficiency_check(),
        draft_text="Draft notification text.",
        draft_citations=[DraftCitation(source="/docs/policy.pdf", section="2.1", score=0.95, sentence="Policy requires recall.")],
        safety_result=make_safety_check(),
        trust_checks=TrustChecks(
            inventory=TrustCheckResult(confidence=0.99),
            rag=TrustCheckResult(confidence=0.95),
        ),
        policy_decision=make_review_decision(),
        approval_status=ApprovalStatus.APPROVED,
        created_at=NOW,
        updated_at=NOW,
    )
    return TicketState(**{**defaults, **overrides})


# EventNormalized

class TestEventNormalized:
    def test_valid_recall(self):
        evt = make_event_normalized()
        assert evt.drug_name == "aspirin"  # normalized to lowercase

    def test_ndc_normalized(self):
        evt = make_event_normalized(ndc="12345678901")
        assert evt.ndc == "12345678901"

    def test_ndc_must_be_11_digits(self):
        with pytest.raises(ValidationError, match="11-digit"):
            make_event_normalized(ndc="1234-567-8901")

    def test_ndc_must_be_digits_only(self):
        with pytest.raises(ValidationError, match="11-digit"):
            make_event_normalized(ndc="1234567890X")

    def test_recall_requires_classification(self):
        with pytest.raises(ValidationError, match="classification is required"):
            make_event_normalized(event_type=EventType.RECALL, classification=None)

    def test_shortage_without_classification_ok(self):
        evt = make_event_normalized(event_type=EventType.SHORTAGE, classification=None)
        assert evt.event_type == EventType.SHORTAGE

    def test_drug_name_stripped_and_lowercased(self):
        evt = make_event_normalized(drug_name="  ASPIRIN  ")
        assert evt.drug_name == "aspirin"

    def test_frozen_model(self):
        evt = make_event_normalized()
        with pytest.raises(ValidationError):
            evt.drug_name = "changed"


# SafetyCheckResult

class TestSafetyCheckResult:
    def test_valid_no_blocks(self):
        result = make_safety_check()
        assert result.needs_action_review is False

    def test_valid_with_blocks(self):
        blocked = BlockedSentence(
            original="Dispose immediately.",
            category=BlockedCategory.DISPOSAL_INSTRUCTION,
            replaced_with="[REMOVED]",
        )
        result = SafetyCheckResult(
            blocked_sentences=[blocked],
            revised_draft="Revised text.",
            needs_action_review=True,
        )
        assert len(result.blocked_sentences) == 1

    def test_blocked_sentences_requires_needs_action_review(self):
        blocked = BlockedSentence(
            original="Do this.",
            category=BlockedCategory.DIRECT_MEDICAL_INSTRUCTION,
            replaced_with="[REMOVED]",
        )
        with pytest.raises(ValidationError, match="needs_action_review must be true"):
            SafetyCheckResult(
                blocked_sentences=[blocked],
                revised_draft="Text.",
                needs_action_review=False,
            )

    def test_needs_action_review_requires_blocked_sentences(self):
        with pytest.raises(ValidationError, match="needs_action_review must be false"):
            SafetyCheckResult(
                blocked_sentences=[],
                revised_draft="Text.",
                needs_action_review=True,
            )


# InventoryMatchResult

class TestInventoryMatchResult:
    def test_valid_match(self):
        result = make_inventory_match()
        assert result.matched is True

    def test_no_match_with_empty_rows(self):
        result = InventoryMatchResult(
            matched=False,
            match_type=MatchType.NO_MATCH,
            match_confidence=0.0,
            matched_rows=[],
        )
        assert result.matched is False

    def test_no_match_with_rows_raises(self):
        with pytest.raises(ValidationError, match="matched_rows must be empty"):
            InventoryMatchResult(
                matched=False,
                match_type=MatchType.NO_MATCH,
                match_confidence=0.0,
                matched_rows=[make_inventory_row()],
            )

    def test_matched_with_no_match_type_raises(self):
        with pytest.raises(ValidationError, match="no_match when matched is true"):
            InventoryMatchResult(
                matched=True,
                match_type=MatchType.NO_MATCH,
                match_confidence=0.9,
                matched_rows=[make_inventory_row()],
            )

    def test_matched_requires_rows(self):
        with pytest.raises(ValidationError, match="matched_rows must not be empty"):
            InventoryMatchResult(
                matched=True,
                match_type=MatchType.EXACT_NDC_MATCH,
                match_confidence=0.95,
                matched_rows=[],
            )

    def test_needs_identity_review_requires_reason(self):
        with pytest.raises(ValidationError, match="identity_review_reason is required"):
            InventoryMatchResult(
                matched=True,
                match_type=MatchType.FUZZY_NAME_MATCH,
                match_confidence=0.7,
                matched_rows=[make_inventory_row()],
                needs_identity_review=True,
                identity_review_reason=None,
            )

    def test_identity_review_with_reason_ok(self):
        result = InventoryMatchResult(
            matched=True,
            match_type=MatchType.FUZZY_NAME_MATCH,
            match_confidence=0.7,
            matched_rows=[make_inventory_row()],
            needs_identity_review=True,
            identity_review_reason="NDC suffix differs.",
        )
        assert result.needs_identity_review is True


# ImpactSummary

class TestImpactSummary:
    def test_valid(self):
        summary = make_impact_summary()
        assert summary.priority == Priority.HIGH

    def test_urgent_requires_reason(self):
        with pytest.raises(ValidationError, match="urgent_reason is required"):
            ImpactSummary(
                affected_departments=[Department.ICU],
                department_breakdown={Department.ICU: 100},
                total_quantity=100,
                priority=Priority.HIGH,
                urgent=True,
                urgent_reason=None,
            )

    def test_urgent_with_reason_ok(self):
        summary = ImpactSummary(
            affected_departments=[Department.ER],
            department_breakdown={Department.ER: 50},
            total_quantity=50,
            priority=Priority.HIGH,
            urgent=True,
            urgent_reason="ICU critical stock.",
        )
        assert summary.urgent is True


# SufficiencyCheckResult

class TestSufficiencyCheckResult:
    def test_valid_sufficient(self):
        result = make_sufficiency_check()
        assert result.evidence_status == EvidenceStatus.SUFFICIENT

    def test_missing_sources_requires_insufficient(self):
        with pytest.raises(ValidationError, match="evidence_status must be insufficient"):
            SufficiencyCheckResult(
                required_sources=[DocumentType.POLICY],
                found_sources=[],
                missing_sources=[DocumentType.POLICY],
                coverage_score=0.0,
                evidence_status=EvidenceStatus.SUFFICIENT,
                needs_evidence_review=True,
            )

    def test_no_missing_sources_requires_sufficient(self):
        with pytest.raises(ValidationError, match="evidence_status must be sufficient"):
            SufficiencyCheckResult(
                required_sources=[DocumentType.POLICY],
                found_sources=[DocumentType.POLICY],
                missing_sources=[],
                coverage_score=1.0,
                evidence_status=EvidenceStatus.INSUFFICIENT,
                needs_evidence_review=False,
            )

    def test_needs_evidence_review_must_match_missing(self):
        with pytest.raises(ValidationError, match="needs_evidence_review must match"):
            SufficiencyCheckResult(
                required_sources=[DocumentType.POLICY],
                found_sources=[],
                missing_sources=[DocumentType.POLICY],
                coverage_score=0.0,
                evidence_status=EvidenceStatus.INSUFFICIENT,
                needs_evidence_review=False,  # should be True
            )


# ReviewDecision

class TestReviewDecision:
    def test_no_impact_close_maps_to_close(self):
        decision = ReviewDecision(
            review_type=ReviewType.NO_IMPACT_CLOSE,
            decision=PolicyDecisionAction.CLOSE,
        )
        assert decision.decision == PolicyDecisionAction.CLOSE

    def test_final_approval_maps_to_request_final_approval(self):
        decision = make_review_decision()
        assert decision.decision == PolicyDecisionAction.REQUEST_FINAL_APPROVAL

    def test_other_review_types_map_to_route_to_hitl(self):
        for review_type in [ReviewType.IDENTITY_REVIEW, ReviewType.EVIDENCE_REVIEW, ReviewType.ACTION_REVIEW]:
            decision = ReviewDecision(
                review_type=review_type,
                decision=PolicyDecisionAction.ROUTE_TO_HITL,
            )
            assert decision.decision == PolicyDecisionAction.ROUTE_TO_HITL

    def test_wrong_decision_for_review_type_raises(self):
        with pytest.raises(ValidationError, match="decision must be"):
            ReviewDecision(
                review_type=ReviewType.NO_IMPACT_CLOSE,
                decision=PolicyDecisionAction.ROUTE_TO_HITL,
            )

    def test_final_approval_with_wrong_decision_raises(self):
        with pytest.raises(ValidationError, match="decision must be"):
            ReviewDecision(
                review_type=ReviewType.FINAL_APPROVAL,
                decision=PolicyDecisionAction.CLOSE,
            )


# TicketState — full composition test

class TestTicketState:
    def test_full_ticket_state_valid(self):
        state = make_ticket_state()
        assert state.ticket_id == "TICKET-001"
        assert state.event_type == EventType.RECALL

    def test_review_type_property(self):
        state = make_ticket_state()
        assert state.review_type == ReviewType.FINAL_APPROVAL

    def test_review_type_none_when_no_decision(self):
        state = make_ticket_state(policy_decision=None)
        assert state.review_type is None

    def test_priority_property(self):
        state = make_ticket_state()
        assert state.priority == Priority.HIGH

    def test_priority_none_when_no_impact_summary(self):
        state = make_ticket_state(impact_summary=None)
        assert state.priority is None

    def test_minimal_ticket_state(self):
        state = TicketState(
            ticket_id="TICKET-MIN",
            event_type=EventType.SHORTAGE,
            created_at=NOW,
            updated_at=NOW,
        )
        assert state.status == TicketStatus.CREATED
        assert state.approval_status == ApprovalStatus.PENDING
        assert state.trust_checks.inventory is None
        assert state.trust_checks.rag is None

    def test_audit_trace_appended(self):
        state = make_ticket_state()
        entry = AuditLogEntry(
            ticket_id="TICKET-001",
            step_name=WorkflowStep.INVENTORY_MATCH,
            input_json={"ndc": "12345678901"},
            output_json={"matched": True},
            timestamp=NOW,
            duration_ms=120,
        )
        state.audit_trace.append(entry)
        assert len(state.audit_trace) == 1
        assert state.audit_trace[0].step_name == WorkflowStep.INVENTORY_MATCH

    def test_event_normalized_ndc_accessible_from_ticket(self):
        state = make_ticket_state()
        assert state.event_normalized.ndc == "12345678901"

    def test_inventory_result_linked_to_ticket(self):
        state = make_ticket_state()
        assert state.inventory_result.matched is True
        assert state.inventory_result.matched_rows[0].department == Department.ICU

    def test_sufficiency_status_accessible_from_ticket(self):
        state = make_ticket_state()
        assert state.sufficiency_check.evidence_status == EvidenceStatus.SUFFICIENT

    def test_safety_result_linked(self):
        state = make_ticket_state()
        assert state.safety_result.needs_action_review is False

    def test_trust_checks_confidence(self):
        state = make_ticket_state()
        assert state.trust_checks.inventory.confidence == 0.99
        assert state.trust_checks.rag.confidence == 0.95

    def test_draft_citations_type(self):
        state = make_ticket_state()
        assert isinstance(state.draft_citations[0], DraftCitation)
        assert state.draft_citations[0].sentence == "Policy requires recall."



# Cross-schema consistency: TicketState with blocked sentences

class TestTicketStateWithActionReview:
    def test_blocked_sentences_trigger_action_review(self):
        blocked = BlockedSentence(
            original="Dispose immediately.",
            category=BlockedCategory.DISPOSAL_INSTRUCTION,
            replaced_with="[REMOVED]",
        )
        safety = SafetyCheckResult(
            blocked_sentences=[blocked],
            revised_draft="Safe version.",
            needs_action_review=True,
        )
        decision = ReviewDecision(
            review_type=ReviewType.ACTION_REVIEW,
            reasons=["Blocked sentence found."],
            decision=PolicyDecisionAction.ROUTE_TO_HITL,
        )
        state = make_ticket_state(
            safety_result=safety,
            policy_decision=decision,
            status=TicketStatus.REVIEW_ROUTED,
            approval_status=ApprovalStatus.PENDING,
        )
        assert state.safety_result.needs_action_review is True
        assert state.review_type == ReviewType.ACTION_REVIEW
        assert state.policy_decision.decision == PolicyDecisionAction.ROUTE_TO_HITL

    def test_insufficient_evidence_triggers_evidence_review(self):
        sufficiency = SufficiencyCheckResult(
            required_sources=[DocumentType.POLICY, DocumentType.SOP],
            found_sources=[DocumentType.POLICY],
            missing_sources=[DocumentType.SOP],
            coverage_score=0.5,
            evidence_status=EvidenceStatus.INSUFFICIENT,
            needs_evidence_review=True,
        )
        decision = ReviewDecision(
            review_type=ReviewType.EVIDENCE_REVIEW,
            reasons=["Missing SOP."],
            decision=PolicyDecisionAction.ROUTE_TO_HITL,
        )
        state = make_ticket_state(
            sufficiency_check=sufficiency,
            policy_decision=decision,
            status=TicketStatus.REVIEW_ROUTED,
        )
        assert state.sufficiency_check.evidence_status == EvidenceStatus.INSUFFICIENT
        assert state.review_type == ReviewType.EVIDENCE_REVIEW

    def test_no_match_triggers_identity_review(self):
        inventory = InventoryMatchResult(
            matched=True,
            match_type=MatchType.FUZZY_NAME_MATCH,
            match_confidence=0.6,
            matched_rows=[make_inventory_row()],
            needs_identity_review=True,
            identity_review_reason="Low confidence fuzzy match.",
        )
        decision = ReviewDecision(
            review_type=ReviewType.IDENTITY_REVIEW,
            reasons=["Fuzzy match only."],
            decision=PolicyDecisionAction.ROUTE_TO_HITL,
        )
        state = make_ticket_state(
            inventory_result=inventory,
            policy_decision=decision,
            status=TicketStatus.REVIEW_ROUTED,
        )
        assert state.inventory_result.needs_identity_review is True
        assert state.review_type == ReviewType.IDENTITY_REVIEW


# API boundary schemas

class TestEventUploadResponse:
    def test_duplicate_rejects_ticket_id(self):
        with pytest.raises(ValidationError, match="ticket_id must be empty"):
            EventUploadResponse(
                event_id="event_001",
                duplicated=True,
                ticket_id="TICKET-001",
            )

    def test_requires_ticket_id_when_not_duplicated(self):
        with pytest.raises(ValidationError, match="ticket_id is required"):
            EventUploadResponse(
                event_id="event_001",
                duplicated=False,
                ticket_id=None,
            )

    def test_rejects_empty_ticket_id(self):
        with pytest.raises(ValidationError, match="ticket_id"):
            EventUploadResponse(
                event_id="event_001",
                duplicated=False,
                ticket_id="",
            )


class TestEvidenceRoutingResult:
    def test_requires_target_document_types(self):
        with pytest.raises(ValidationError, match="target_document_types"):
            EvidenceRoutingResult(
                target_document_types=[],
                target_sections=["recall_response"],
            )


class TestChatRequest:
    def test_rejects_empty_session_id(self):
        with pytest.raises(ValidationError, match="session_id"):
            ChatRequest(user_query="What happened?", session_id="")


class TestIdentityReviewPayload:
    def test_rejects_invalid_affected_department(self):
        with pytest.raises(ValidationError, match="affected_departments"):
            IdentityReviewPayload(
                ticket_id="TICKET-001",
                approval_status=ApprovalStatus.PENDING,
                summary=TicketSummary(
                    drug_name="aspirin",
                    event_type=EventType.RECALL,
                    classification=Classification.CLASS_I,
                    priority=Priority.HIGH,
                ),
                identity_issue=IdentityIssue(
                    input_ndc="12345678901",
                    matched_ndc="12345678902",
                    match_confidence=0.7,
                    reason="NDC mismatch.",
                ),
                affected_departments=["INVALID"],
                total_quantity=100,
            )


class TestEvalResult:
    def test_rejects_negative_duration_ms(self):
        with pytest.raises(ValidationError, match="duration_ms"):
            EvalResult(
                scenario_id="scenario_001",
                passed=False,
                expected_review_type=ReviewType.FINAL_APPROVAL,
                actual_review_type=ReviewType.ACTION_REVIEW,
                expected_evidence_status=EvidenceStatus.SUFFICIENT,
                actual_evidence_status=EvidenceStatus.SUFFICIENT,
                expected_has_blocked_sentences=False,
                actual_has_blocked_sentences=True,
                workflow_steps_completed=3,
                duration_ms=-1,
                failure_reason="Unexpected action review.",
            )
