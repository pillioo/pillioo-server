from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.db.models.audit_log_model import AuditLog
from app.db.models.report_version_model import ReportVersion
from app.db.models.ticket import Ticket
from app.orchestration.retrieval_identity import resolve_retrieval_drug_name
from app.orchestration.service import run_ticket_workflow
from app.orchestration.steps import coerce_inventory_row_ndc, normalize_inventory_match_payload, run_evidence_step
from app.orchestration.tickets import build_event_idempotency_key
from app.rag.models import (
    EvidenceChunk as RagEvidenceChunk,
    EvidencePlan,
    EvidenceResult as RagEvidenceResult,
    EvidenceTarget,
    RetrievalContext,
    SufficiencyResult,
)
from app.schemas.common import (
    Classification,
    EvidenceStatus,
    EventType,
    MatchType,
    PolicyDecisionAction,
    ReviewType,
    TicketStatus,
)
from app.schemas.event import EventNormalized, SafetyCheckResult
from app.schemas.evidence import SufficiencyCheckResult
from app.schemas.inventory import InventoryMatchResult
from app.schemas.workflow import TicketState
from app.workflow.routing import aggregate_policy_decision
from app.workflow.state import WorkflowStage, stage_for_status


class FakeSession:
    def __init__(self) -> None:
        self.objects = []
        self.committed = False
        self._next_id = 1

    def add(self, obj) -> None:
        self.objects.append(obj)

    def flush(self) -> None:
        for obj in self.objects:
            if getattr(obj, "id", None) is None:
                obj.id = self._next_id
                self._next_id += 1
            if getattr(obj, "created_at", None) is None:
                obj.created_at = datetime.now(timezone.utc)

    def refresh(self, obj) -> None:
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(timezone.utc)

    def commit(self) -> None:
        self.committed = True

    def query(self, model):
        return FakeQuery([obj for obj in self.objects if isinstance(obj, model)])


class FakeQuery:
    def __init__(self, objects) -> None:
        self.objects = objects
        self.filters = []

    def filter(self, *filters):
        self.filters.extend(filters)
        return self

    def first(self):
        for obj in self.objects:
            if all(_matches_filter(obj, item) for item in self.filters):
                return obj
        return None


def _matches_filter(obj, expression) -> bool:
    left = getattr(expression, "left", None)
    right = getattr(expression, "right", None)
    field = getattr(left, "key", None)
    value = getattr(right, "value", None)
    if field is None:
        return True
    return getattr(obj, field) == value


class FakeEvidenceService:
    def __init__(self, sufficiency: SufficiencyResult | None = None) -> None:
        self.calls = []
        self.sufficiency = sufficiency or SufficiencyResult(
            required_document_types=["recall_notice", "policy", "sop"],
            found_document_types=["recall_notice", "policy", "sop"],
            missing_document_types=[],
            weak_document_types=[],
            coverage_score=1.0,
            evidence_status=EvidenceStatus.SUFFICIENT.value,
            needs_evidence_review=False,
            citations_ready=True,
        )

    def retrieve(self, *, query, context=None, top_k=5, filter_override=None):
        self.calls.append(
            {
                "query": query,
                "context": context,
                "top_k": top_k,
                "filter_override": filter_override,
            }
        )
        plan = EvidencePlan(
            event_type="recall",
            targets=[
                EvidenceTarget("recall_notice"),
                EvidenceTarget("policy"),
                EvidenceTarget("sop"),
            ],
        )
        chunks = [
            RagEvidenceChunk(
                chunk_id="chunk-1",
                chunk_index=0,
                content="Recall evidence text",
                document_id="doc-1",
                document_type="recall_notice",
                event_type="recall",
                section="recall_notice",
                source_path="recall.md",
                score=0.91,
                drug_name="midazolam",
                normalized_drug_name="midazolam",
                recall_number="D-123-2026",
            ),
            RagEvidenceChunk(
                chunk_id="chunk-2",
                chunk_index=0,
                content="Policy evidence text",
                document_id="doc-2",
                document_type="policy",
                event_type="recall",
                section="required_actions",
                source_path="policy.md",
                score=0.88,
                drug_name="midazolam",
                normalized_drug_name="midazolam",
            ),
            RagEvidenceChunk(
                chunk_id="chunk-3",
                chunk_index=0,
                content="SOP evidence text",
                document_id="doc-3",
                document_type="sop",
                event_type="recall",
                section="procedure",
                source_path="sop.md",
                score=0.87,
                drug_name="midazolam",
                normalized_drug_name="midazolam",
            ),
        ]
        return RagEvidenceResult(
            query=query,
            context=context or RetrievalContext(),
            plan=plan,
            chunks=chunks,
            sufficiency=self.sufficiency,
        )


class FailingEvidenceService:
    def retrieve(self, **kwargs):
        raise RuntimeError("milvus timeout")


class FailingDraftGenerator:
    def generate(self, **kwargs):
        raise ValueError("draft model rejected input")


def event() -> EventNormalized:
    return EventNormalized(
        event_id="D-123-2026",
        event_type=EventType.RECALL,
        drug_name="midazolam",
        ndc="00641601441",
        lot="LOT-A",
        classification=Classification.CLASS_I,
        status="ongoing",
        recall_number="D-123-2026",
        product_description="MIDAZOLAM HCl 1mg/mL",
    )


def combo_event() -> EventNormalized:
    return EventNormalized(
        event_id="D-999-2026",
        event_type=EventType.RECALL,
        drug_name="piperacillin and tazobactam",
        ndc="35203213915",
        lot="LOT-A",
        classification=Classification.CLASS_II,
        status="ongoing",
        recall_number="D-999-2026",
        product_description="Piperacillin Sodium and Tazobactam Sodium 4.5g powder for injection",
    )


def sodium_chloride_event() -> EventNormalized:
    return EventNormalized(
        event_id="D-998-2026",
        event_type=EventType.RECALL,
        drug_name="sodium chloride",
        ndc="00641601441",
        lot="LOT-A",
        classification=Classification.CLASS_II,
        status="ongoing",
        recall_number="D-998-2026",
        product_description="Sodium Chloride 0.9% Injection",
    )


def minimal_state(**overrides) -> TicketState:
    defaults = {
        "ticket_id": "T-001",
        "event_type": EventType.RECALL,
        "classification": Classification.CLASS_I,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return TicketState(**defaults)


def test_policy_aggregator_routes_no_match_to_close() -> None:
    state = minimal_state(
        classification=Classification.CLASS_II,
        inventory_result=InventoryMatchResult(
            matched=False,
            match_type=MatchType.NO_MATCH,
            match_confidence=0.0,
            matched_rows=[],
        ),
        sufficiency_check=sufficient_evidence(),
    )

    decision = aggregate_policy_decision(state)

    assert decision.review_type == ReviewType.NO_IMPACT_CLOSE
    assert decision.decision == PolicyDecisionAction.CLOSE


def sufficient_evidence(**overrides) -> SufficiencyCheckResult:
    defaults = {
        "required_sources": ["policy", "sop", "recall_notice"],
        "found_sources": ["policy", "sop", "recall_notice"],
        "missing_sources": [],
        "weak_sources": [],
        "coverage_score": 1.0,
        "evidence_status": EvidenceStatus.SUFFICIENT,
        "needs_evidence_review": False,
        "citations_ready": True,
    }
    defaults.update(overrides)
    return SufficiencyCheckResult(**defaults)


def test_policy_aggregator_prioritizes_evidence_review_over_action_review() -> None:
    state = minimal_state(
        inventory_result=InventoryMatchResult(
            matched=True,
            match_type=MatchType.EXACT_NDC_MATCH,
            match_confidence=1.0,
            matched_rows=[
                {
                    "inventory_id": "INV-001",
                    "drug_name": "midazolam",
                    "ndc": "00641601441",
                    "quantity": 1,
                    "department": "ICU",
                    "days_remaining": 2,
                }
            ],
        ),
        sufficiency_check=SufficiencyCheckResult(
            required_sources=["policy", "sop", "recall_notice"],
            found_sources=["policy", "sop"],
            missing_sources=["recall_notice"],
            coverage_score=0.67,
            evidence_status=EvidenceStatus.INSUFFICIENT,
            needs_evidence_review=True,
        ),
        safety_result=SafetyCheckResult(
            blocked_sentences=[
                {
                    "original": "Stop immediately.",
                    "category": "direct_medical_instruction",
                    "replaced_with": "Ask pharmacist.",
                }
            ],
            revised_draft="Ask pharmacist.",
            needs_action_review=True,
        ),
    )

    decision = aggregate_policy_decision(state)

    assert decision.review_type == ReviewType.EVIDENCE_REVIEW


def test_policy_aggregator_routes_citations_not_ready_to_evidence_review() -> None:
    state = minimal_state(
        inventory_result=matched_inventory(),
        sufficiency_check=sufficient_evidence(
            citations_ready=False,
            evidence_status=EvidenceStatus.INSUFFICIENT,
            needs_evidence_review=True,
            failure_reasons=[{"reason": "citation_not_ready"}],
        ),
    )

    assert aggregate_policy_decision(state).review_type == ReviewType.EVIDENCE_REVIEW


def test_policy_aggregator_routes_low_coverage_to_evidence_review() -> None:
    state = minimal_state(
        inventory_result=matched_inventory(),
        sufficiency_check=sufficient_evidence(coverage_score=0.79),
    )

    assert aggregate_policy_decision(state).review_type == ReviewType.EVIDENCE_REVIEW


def test_policy_aggregator_allows_final_approval_when_guardrails_pass() -> None:
    state = minimal_state(
        inventory_result=matched_inventory(),
        sufficiency_check=sufficient_evidence(),
        safety_result=SafetyCheckResult(
            blocked_sentences=[],
            revised_draft="Safe draft.",
            needs_action_review=False,
        ),
    )

    assert aggregate_policy_decision(state).review_type == ReviewType.FINAL_APPROVAL


def test_class_i_no_match_does_not_auto_close() -> None:
    state = minimal_state(
        classification=Classification.CLASS_I,
        inventory_result=InventoryMatchResult(
            matched=False,
            match_type=MatchType.NO_MATCH,
            match_confidence=0.0,
            matched_rows=[],
        ),
        sufficiency_check=sufficient_evidence(),
    )

    assert aggregate_policy_decision(state).review_type == ReviewType.IDENTITY_REVIEW


def test_no_match_with_identity_uncertainty_routes_to_identity_review() -> None:
    state = minimal_state(
        classification=Classification.CLASS_II,
        inventory_result=InventoryMatchResult(
            matched=False,
            match_type=MatchType.NO_MATCH,
            match_confidence=0.0,
            matched_rows=[],
            needs_identity_review=True,
            identity_review_reason="Inventory stale.",
        ),
        sufficiency_check=sufficient_evidence(),
    )

    assert aggregate_policy_decision(state).review_type == ReviewType.IDENTITY_REVIEW


def matched_inventory() -> InventoryMatchResult:
    return InventoryMatchResult(
        matched=True,
        match_type=MatchType.EXACT_NDC_MATCH,
        match_confidence=1.0,
        matched_rows=[
            {
                "inventory_id": "INV-001",
                "drug_name": "midazolam",
                "ndc": "00641601441",
                "quantity": 1,
                "department": "ICU",
                "days_remaining": 2,
            }
        ],
    )


def test_run_ticket_workflow_persists_state_and_audit_with_fake_evidence() -> None:
    db = FakeSession()
    evidence_service = FakeEvidenceService()

    result = run_ticket_workflow(db=db, event=event(), evidence_service=evidence_service)

    assert db.committed is True
    assert result.ticket.ticket_id.startswith("T-")
    assert result.ticket.status == TicketStatus.REVIEW_ROUTED.value
    assert result.ticket.inventory_result["matched"] is True
    assert result.ticket.sufficiency_check["evidence_status"] == EvidenceStatus.SUFFICIENT.value
    assert result.ticket.policy_decision["review_type"] == ReviewType.FINAL_APPROVAL.value
    assert result.state.policy_decision.review_type == ReviewType.FINAL_APPROVAL
    assert evidence_service.calls[0]["context"].normalized_drug_name == "midazolam"

    audit_steps = [getattr(obj, "step_name", None) for obj in db.objects]
    assert "inventory_match" in audit_steps
    assert "evidence_retrieval" in audit_steps
    assert "policy_aggregation" in audit_steps

    evidence_audit = next(obj for obj in db.objects if isinstance(obj, AuditLog) and obj.step_name == "evidence_retrieval")
    assert evidence_audit.output_json["query"]
    assert evidence_audit.output_json["coverage_score"] == 1.0
    assert evidence_audit.output_json["chunk_count"] == 3
    assert evidence_audit.output_json["citations_ready"] is True
    assert evidence_audit.output_json["failure_reasons"] == []
    assert "retrieval_trace" in evidence_audit.output_json

    safety_audit = next(obj for obj in db.objects if isinstance(obj, AuditLog) and obj.step_name == "safety_check")
    assert safety_audit.input_json["lang"] == "both"

    policy_audit = next(obj for obj in db.objects if isinstance(obj, AuditLog) and obj.step_name == "policy_aggregation")
    assert policy_audit.output_json["review_type"] == ReviewType.FINAL_APPROVAL.value
    assert policy_audit.output_json["final_routing_reason"]


def test_run_ticket_workflow_is_idempotent_for_same_event() -> None:
    db = FakeSession()
    evidence_service = FakeEvidenceService()

    first = run_ticket_workflow(db=db, event=event(), evidence_service=evidence_service)
    second = run_ticket_workflow(db=db, event=event(), evidence_service=evidence_service)

    tickets = [obj for obj in db.objects if isinstance(obj, Ticket)]
    assert len(tickets) == 1
    assert second.ticket.id == first.ticket.id
    assert second.created is False
    assert second.state.inventory_result is not None
    assert second.state.policy_decision is not None
    assert build_event_idempotency_key(event()) == "recall|D-123-2026|D-123-2026|00641601441|LOT-A"


def test_evidence_failure_marks_ticket_for_manual_review_and_commits() -> None:
    db = FakeSession()

    with pytest.raises(RuntimeError, match="milvus timeout"):
        run_ticket_workflow(db=db, event=event(), evidence_service=FailingEvidenceService())

    ticket = next(obj for obj in db.objects if isinstance(obj, Ticket))
    assert db.committed is True
    assert ticket.status == TicketStatus.WORKFLOW_FAILED.value
    assert ticket.workflow_stage == WorkflowStage.PENDING_MANUAL_REVIEW.value

    failure_audit = next(obj for obj in db.objects if isinstance(obj, AuditLog) and obj.step_name == "evidence_retrieval")
    assert failure_audit.output_json["step_status"] == "failed"
    assert failure_audit.output_json["error_type"] == "RuntimeError"
    assert failure_audit.output_json["retryable"] is True


def test_draft_failure_marks_ticket_for_manual_review_and_commits() -> None:
    db = FakeSession()

    with pytest.raises(ValueError, match="draft model rejected input"):
        run_ticket_workflow(
            db=db,
            event=event(),
            evidence_service=FakeEvidenceService(),
            draft_generator=FailingDraftGenerator(),
        )

    ticket = next(obj for obj in db.objects if isinstance(obj, Ticket))
    assert db.committed is True
    assert ticket.status == TicketStatus.WORKFLOW_FAILED.value
    assert ticket.workflow_stage == WorkflowStage.PENDING_MANUAL_REVIEW.value
    failure_audit = next(obj for obj in db.objects if isinstance(obj, AuditLog) and obj.step_name == "draft_generation")
    assert failure_audit.output_json["retryable"] is False


def test_failed_ticket_retries_when_same_event_is_processed_again() -> None:
    db = FakeSession()

    with pytest.raises(RuntimeError):
        run_ticket_workflow(db=db, event=event(), evidence_service=FailingEvidenceService())

    result = run_ticket_workflow(db=db, event=event(), evidence_service=FakeEvidenceService())

    tickets = [obj for obj in db.objects if isinstance(obj, Ticket)]
    assert len(tickets) == 1
    assert result.created is False
    assert result.ticket.status == TicketStatus.REVIEW_ROUTED.value
    assert result.ticket.workflow_stage == WorkflowStage.PENDING_REVIEW.value


def test_successful_workflow_saves_draft_v1_report_version() -> None:
    db = FakeSession()

    result = run_ticket_workflow(db=db, event=event(), evidence_service=FakeEvidenceService())

    versions = [obj for obj in db.objects if isinstance(obj, ReportVersion)]
    assert len(versions) == 1
    assert versions[0].ticket_id == result.ticket.id
    assert versions[0].version_tag == "draft_v1"
    assert versions[0].report_text == result.ticket.draft_text


def test_retrieval_context_uses_event_normalizer_for_drug_name() -> None:
    db = FakeSession()
    evidence_service = FakeEvidenceService()
    current_event = combo_event()
    ticket = Ticket(
        ticket_id="T-999",
        event_type=current_event.event_type.value,
        drug_name=current_event.drug_name,
        ndc=current_event.ndc,
        lot=current_event.lot,
        classification=current_event.classification.value,
        status=TicketStatus.INVENTORY_CHECKED.value,
        workflow_stage=WorkflowStage.PENDING_EVIDENCE.value,
    )
    ticket.id = 1
    state = minimal_state(
        event_type=current_event.event_type,
        classification=current_event.classification,
        status=TicketStatus.INVENTORY_CHECKED,
        event_normalized=current_event,
    )

    run_evidence_step(db=db, ticket=ticket, state=state, evidence_service=evidence_service, top_k=5)

    assert evidence_service.calls[0]["context"].drug_name == "piperacillin and tazobactam"
    assert evidence_service.calls[0]["context"].normalized_drug_name == "piperacillin / tazobactam"


def test_retrieval_identity_reuses_event_normalizer_protected_compounds() -> None:
    assert resolve_retrieval_drug_name(sodium_chloride_event()) == "sodium chloride"


def test_inventory_row_ndc_coercion_for_schema_handoff() -> None:
    assert coerce_inventory_row_ndc(641601441) == "00641601441"
    assert coerce_inventory_row_ndc(641601441.0) == "00641601441"
    normalized = normalize_inventory_match_payload({"matched_rows": [{"ndc": 641601441.0}]})
    assert normalized["matched_rows"][0]["ndc"] == "00641601441"


def test_stage_for_status_transitions() -> None:
    assert stage_for_status(TicketStatus.CREATED) == WorkflowStage.PENDING_INVENTORY
    assert stage_for_status(TicketStatus.INVENTORY_CHECKED) == WorkflowStage.PENDING_EVIDENCE
    assert stage_for_status(TicketStatus.EVIDENCE_RETRIEVED) == WorkflowStage.PENDING_DRAFT
    assert stage_for_status(TicketStatus.DRAFT_GENERATED) == WorkflowStage.PENDING_SAFETY
    assert stage_for_status(TicketStatus.SAFETY_CHECKED) == WorkflowStage.PENDING_POLICY_AGGREGATION
    assert stage_for_status(TicketStatus.REVIEW_ROUTED) == WorkflowStage.PENDING_REVIEW
    assert stage_for_status(TicketStatus.CLOSED) == WorkflowStage.CLOSED
