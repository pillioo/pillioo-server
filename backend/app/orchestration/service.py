from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy.orm import Session

from app.db.models.ticket import Ticket
from app.orchestration.draft import LLMDraftGenerator
from app.orchestration.report_grounding import (
    affected_product_from_state,
    evidence_summary_from_state,
    inventory_impact_from_state,
)
from app.orchestration.steps import (
    evidence_gate_allows_draft,
    run_draft_step,
    run_evidence_gate_step,
    run_evidence_step,
    run_inventory_step,
    run_policy_aggregation_step,
    run_safety_step,
    run_workflow_step,
    write_skipped_workflow_step,
)
from app.orchestration.tickets import create_ticket_record, get_or_create_ticket_record
from app.orchestration.state import ticket_to_state
from app.rag.models import EvidenceResult as RagEvidenceResult
from app.rag.models import RetrievalContext
from app.schemas.common import TicketStatus, WorkflowStep
from app.schemas.event import EventNormalized
from app.schemas.evidence import DraftCitation, EvidenceResult
from app.schemas.report import DraftReport
from app.schemas.workflow import TicketState, TrustChecks
from app.workflow.state import WorkflowStage, can_rerun_workflow


class EvidenceRetrievalService(Protocol):
    def retrieve(
        self,
        *,
        query: str,
        context: RetrievalContext | None = None,
        top_k: int = 5,
        filter_override: str | None = None,
    ) -> RagEvidenceResult:
        ...


class DraftGenerator(Protocol):
    def generate(
        self,
        *,
        state: TicketState,
        evidence_result: EvidenceResult,
    ) -> DraftReport:
        ...


@dataclass(frozen=True)
class OrchestrationResult:
    ticket: Ticket
    state: TicketState
    created: bool = True


class SimpleDraftGenerator:
    """Deterministic, non-LLM DraftGenerator used as a test/offline fallback.
    Returns the same structured DraftReport shape as LLMDraftGenerator, just
    with a fixed, templated narrative instead of a model-generated one."""

    def generate(
        self,
        *,
        state: TicketState,
        evidence_result: EvidenceResult,
    ) -> DraftReport:
        drug_name = state.event_normalized.drug_name if state.event_normalized else "the affected drug"
        classification = state.classification.value if state.classification else "unclassified"
        event_type = state.event_type.value if state.event_type else "event"

        recommended_action = "Hold affected inventory for pharmacist review before further action."
        citations = [
            DraftCitation(
                source=citation.source,
                section=citation.section,
                score=citation.score,
                sentence=recommended_action,
            )
            for citation in evidence_result.citations[:3]
        ]

        return DraftReport(
            title=f"{drug_name} {classification} {event_type} review draft",
            summary=f"{drug_name} {classification} {event_type} notice.",
            affected_product=affected_product_from_state(state),
            event_classification=state.classification.value if state.classification else None,
            inventory_impact=inventory_impact_from_state(state),
            evidence_summary=evidence_summary_from_state(state),
            recommended_review_action=recommended_action,
            citations=citations,
        )


def run_ticket_workflow(
    *,
    db: Session,
    event: EventNormalized,
    evidence_service: EvidenceRetrievalService,
    draft_generator: DraftGenerator | None = None,
    top_k: int = 5,
) -> OrchestrationResult:
    ticket, created = get_or_create_ticket_record(db, event)
    state = build_initial_state(ticket, event)

    # CREATED means the ticket was persisted but the workflow never ran yet
    # (e.g. via /events/upload) -- treat it like a fresh run, not "already done".
    already_processed = not created and not can_rerun_workflow(ticket.status)
    if already_processed:
        return OrchestrationResult(ticket=ticket, state=ticket_to_state(db, ticket), created=False)

    if not created and ticket.status == TicketStatus.WORKFLOW_FAILED.value:
        reset_failed_ticket_for_retry(ticket)
        state = build_initial_state(ticket, event)

    state = run_workflow_step(
        db=db,
        ticket=ticket,
        step_name=WorkflowStep.INVENTORY_MATCH,
        func=lambda: run_inventory_step(db, ticket, state),
    )
    state = run_workflow_step(
        db=db,
        ticket=ticket,
        step_name=WorkflowStep.EVIDENCE_RETRIEVAL,
        func=lambda: run_evidence_step(db, ticket, state, evidence_service=evidence_service, top_k=top_k),
    )
    state = run_workflow_step(
        db=db,
        ticket=ticket,
        step_name=WorkflowStep.SUFFICIENCY_CHECK,
        func=lambda: run_evidence_gate_step(db, ticket, state),
    )
    if evidence_gate_allows_draft(state):
        state = run_workflow_step(
            db=db,
            ticket=ticket,
            step_name=WorkflowStep.DRAFT_GENERATION,
            func=lambda: run_draft_step(db, ticket, state, draft_generator=draft_generator or LLMDraftGenerator()),
        )
        state = run_workflow_step(
            db=db,
            ticket=ticket,
            step_name=WorkflowStep.SAFETY_CHECK,
            func=lambda: run_safety_step(db, ticket, state),
        )
    else:
        write_skipped_workflow_step(
            db=db,
            ticket=ticket,
            step_name=WorkflowStep.DRAFT_GENERATION,
            reason="insufficient_evidence",
            input_json={"evidence_status": state.sufficiency_check.evidence_status.value if state.sufficiency_check else None},
        )
        write_skipped_workflow_step(
            db=db,
            ticket=ticket,
            step_name=WorkflowStep.SAFETY_CHECK,
            reason="draft_generation_skipped",
            input_json={"draft_text_present": bool(state.draft_text)},
        )
    state = run_workflow_step(
        db=db,
        ticket=ticket,
        step_name=WorkflowStep.POLICY_AGGREGATION,
        func=lambda: run_policy_aggregation_step(db, ticket, state),
    )

    db.commit()
    return OrchestrationResult(ticket=ticket, state=state, created=created)


def build_initial_state(ticket: Ticket, event: EventNormalized) -> TicketState:
    now = datetime.now(timezone.utc)
    return TicketState(
        ticket_id=ticket.ticket_id,
        event_type=event.event_type,
        classification=event.classification,
        status=TicketStatus.CREATED,
        event_normalized=event,
        trust_checks=TrustChecks(),
        created_at=ticket.created_at or now,
        updated_at=ticket.updated_at or now,
    )


def reset_failed_ticket_for_retry(ticket: Ticket) -> None:
    ticket.status = TicketStatus.CREATED.value
    ticket.workflow_stage = WorkflowStage.PENDING_INVENTORY.value
