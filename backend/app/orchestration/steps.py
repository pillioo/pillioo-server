from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Callable, TypeVar

from sqlalchemy.orm import Session

from app.audit.logger import write_audit_log
from app.db.models.ticket import Ticket
from app.event.safety import draft_safety_check
from app.inventory.impact import assess_impact
from app.inventory.matcher import inventory_match
from app.orchestration.retrieval_identity import resolve_retrieval_drug_name
from app.report.versioning import save_report_version
from app.rag.adapter import to_ticket_state_fields
from app.rag.evidence_snapshot import create_ticket_evidence_snapshot
from app.rag.models import RetrievalContext
from app.schemas.common import ReportVersionTag, TicketStatus, WorkflowStep
from app.schemas.evidence import EvidenceResult
from app.schemas.inventory import ImpactSummary, InventoryMatchResult
from app.schemas.workflow import TicketState
from app.workflow.policy import requires_evidence_review
from app.workflow.routing import aggregate_policy_decision, policy_audit_output
from app.workflow.state import WorkflowStage, stage_for_status


StepResult = TypeVar("StepResult")


def run_workflow_step(
    *,
    db: Session,
    ticket: Ticket,
    step_name: WorkflowStep,
    func: Callable[[], StepResult],
) -> StepResult:
    started = time.perf_counter()
    try:
        return func()
    except Exception as exc:
        duration_ms = _elapsed_ms(started)
        mark_ticket_failed(ticket)
        write_audit_log(
            db=db,
            ticket_id=ticket.id,
            step_name=step_name,
            input_json={"step_status": "started"},
            output_json={
                "step_status": "failed",
                "duration_ms": duration_ms,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "retryable": is_retryable_error(exc),
            },
            duration_ms=duration_ms,
        )
        db.commit()
        raise


def mark_ticket_failed(ticket: Ticket) -> None:
    # Failed executions are retryable by reprocessing the same source event.
    # Normal HITL routing uses REVIEW_ROUTED/PENDING_REVIEW instead.
    ticket.status = TicketStatus.WORKFLOW_FAILED.value
    ticket.workflow_stage = WorkflowStage.PENDING_MANUAL_REVIEW.value


def run_inventory_step(db: Session, ticket: Ticket, state: TicketState) -> TicketState:
    started = time.perf_counter()
    event = state.event_normalized
    raw_match = normalize_inventory_match_payload(inventory_match(event.drug_name, event.ndc, event.lot or ""))
    raw_impact = assess_impact(raw_match)

    inventory_result = InventoryMatchResult(**raw_match)
    impact_summary = ImpactSummary(**raw_impact)
    updated = state.model_copy(
        update={
            "inventory_result": inventory_result,
            "impact_summary": impact_summary,
            "status": TicketStatus.INVENTORY_CHECKED,
            "updated_at": datetime.now(timezone.utc),
        }
    )

    ticket.inventory_result = inventory_result.model_dump(mode="json")
    ticket.impact_summary = impact_summary.model_dump(mode="json")
    ticket.priority = impact_summary.priority.value
    ticket.status = TicketStatus.INVENTORY_CHECKED.value
    ticket.workflow_stage = stage_for_status(TicketStatus.INVENTORY_CHECKED).value

    write_audit_log(
        db=db,
        ticket_id=ticket.id,
        step_name=WorkflowStep.INVENTORY_MATCH,
        input_json={"drug_name": event.drug_name, "ndc": event.ndc, "lot": event.lot},
        output_json={
            "step_status": "succeeded",
            "inventory_result": ticket.inventory_result,
            "impact_summary": ticket.impact_summary,
        },
        duration_ms=_elapsed_ms(started),
    )
    return updated


def run_evidence_step(
    db: Session,
    ticket: Ticket,
    state: TicketState,
    *,
    evidence_service,
    top_k: int,
) -> TicketState:
    started = time.perf_counter()
    event = state.event_normalized
    query = build_evidence_query(state)
    # Do not use fallback event_id values as recall_number strong filters.
    recall_number = None if event.recall_number_is_fallback else event.recall_number
    rag_result = evidence_service.retrieve(
        query=query,
        context=RetrievalContext(
            event_type=event.event_type.value,
            drug_name=event.drug_name,
            normalized_drug_name=resolve_retrieval_drug_name(event),
            ndc=[event.ndc] if event.ndc else [],
            lot=event.lot,
            recall_number=recall_number,
            classification=event.classification.value if event.classification else None,
        ),
        top_k=top_k,
    )
    evidence_result, sufficiency_check = to_ticket_state_fields(rag_result)
    updated = state.model_copy(
        update={
            "evidence_result": evidence_result,
            "sufficiency_check": sufficiency_check,
            "status": TicketStatus.EVIDENCE_RETRIEVED,
            "updated_at": datetime.now(timezone.utc),
        }
    )

    ticket.evidence_result = evidence_result.model_dump(mode="json")
    ticket.sufficiency_check = sufficiency_check.model_dump(mode="json")
    ticket.status = TicketStatus.EVIDENCE_RETRIEVED.value
    ticket.workflow_stage = stage_for_status(TicketStatus.EVIDENCE_RETRIEVED).value

    write_audit_log(
        db=db,
        ticket_id=ticket.id,
        step_name=WorkflowStep.EVIDENCE_RETRIEVAL,
        input_json={
            "query": query,
            "top_k": top_k,
            "event_type": event.event_type.value,
            "drug_name": event.drug_name,
            "retrieval_context": retrieval_context_json(rag_result.context),
        },
        output_json=evidence_audit_output(
            query=query,
            top_k=top_k,
            rag_result=rag_result,
            evidence_result=evidence_result,
            sufficiency_check=sufficiency_check,
        ),
        duration_ms=_elapsed_ms(started),
    )
    return updated


def run_draft_step(
    db: Session,
    ticket: Ticket,
    state: TicketState,
    *,
    draft_generator,
) -> TicketState:
    started = time.perf_counter()
    report = draft_generator.generate(
        state=state,
        evidence_result=state.evidence_result or EvidenceResult(),
    )
    # draft_text/draft_citations stay as a derived, flattened view of the
    # structured report so existing consumers (chat prompt context,
    # draft_safety_check, review payloads) don't need to change.
    draft_text = report.to_display_text()
    draft_citations = report.citations
    updated = state.model_copy(
        update={
            "draft_report": report,
            "draft_text": draft_text,
            "draft_citations": draft_citations,
            "status": TicketStatus.DRAFT_GENERATED,
            "updated_at": datetime.now(timezone.utc),
        }
    )

    ticket.draft_text = draft_text
    ticket.draft_citations = [citation.model_dump(mode="json") for citation in draft_citations]
    # Persist draft_v1 as a structured report (report_json) so the follow-up
    # review/approval flow, versioning, and any future frontend can consume
    # the structured body -- report_text is still derived for plain-text
    # consumers of the existing approval/report flow.
    save_report_version(
        db=db,
        ticket_id=ticket.id,
        version_tag=ReportVersionTag.DRAFT_V1,
        report=report,
        created_by="workflow",
    )
    ticket.status = TicketStatus.DRAFT_GENERATED.value
    ticket.workflow_stage = stage_for_status(TicketStatus.DRAFT_GENERATED).value

    write_audit_log(
        db=db,
        ticket_id=ticket.id,
        step_name=WorkflowStep.DRAFT_GENERATION,
        input_json={"top_chunks": ticket.evidence_result.get("top_chunks", []) if ticket.evidence_result else []},
        output_json={"step_status": "succeeded", "draft_text": draft_text, "draft_citations": ticket.draft_citations},
        duration_ms=_elapsed_ms(started),
    )
    return updated


def run_evidence_gate_step(db: Session, ticket: Ticket, state: TicketState) -> TicketState:
    started = time.perf_counter()
    gate = evidence_gate_output(state)
    # The gate is deliberately a routing/audit decision, not a hard workflow
    # failure. Insufficient evidence should route to pharmacist review instead
    # of generating a weak draft or marking the ticket retryable.
    if not gate["can_generate_draft"]:
        ticket.workflow_stage = WorkflowStage.PENDING_POLICY_AGGREGATION.value

    gate_audit_log = write_audit_log(
        db=db,
        ticket_id=ticket.id,
        step_name=WorkflowStep.SUFFICIENCY_CHECK,
        input_json={
            "evidence_status": state.sufficiency_check.evidence_status.value if state.sufficiency_check else None,
            "citations_ready": state.sufficiency_check.citations_ready if state.sufficiency_check else None,
        },
        output_json={"step_status": "succeeded", **gate},
        duration_ms=_elapsed_ms(started),
    )
    create_ticket_evidence_snapshot(
        db=db,
        ticket=ticket,
        state=state,
        source_audit_log=gate_audit_log,
    )
    return state


def evidence_gate_allows_draft(state: TicketState) -> bool:
    return not requires_evidence_review(state.sufficiency_check)


def evidence_gate_output(state: TicketState) -> dict:
    sufficiency = state.sufficiency_check
    can_generate = evidence_gate_allows_draft(state)
    if sufficiency is None:
        return {
            "gate_status": "blocked",
            "can_generate_draft": False,
            "skip_reason": "missing_sufficiency_check",
            "failure_reasons": [{"reason": "missing_sufficiency_check"}],
            "missing_sources": [],
            "weak_sources": [],
            "citations_ready": False,
        }

    return {
        "gate_status": "passed" if can_generate else "blocked",
        "can_generate_draft": can_generate,
        "skip_reason": "" if can_generate else "insufficient_evidence",
        "evidence_status": sufficiency.evidence_status.value,
        "coverage_score": sufficiency.coverage_score,
        "missing_sources": [source.value for source in sufficiency.missing_sources],
        "weak_sources": [source.value for source in sufficiency.weak_sources],
        "failure_reasons": sufficiency.failure_reasons,
        "citations_ready": sufficiency.citations_ready,
    }


def write_skipped_workflow_step(
    *,
    db: Session,
    ticket: Ticket,
    step_name: WorkflowStep,
    reason: str,
    input_json: dict | None = None,
) -> None:
    started = time.perf_counter()
    write_audit_log(
        db=db,
        ticket_id=ticket.id,
        step_name=step_name,
        input_json=input_json or {},
        output_json={
            "step_status": "skipped",
            "reason": reason,
        },
        duration_ms=_elapsed_ms(started),
    )


def run_safety_step(db: Session, ticket: Ticket, state: TicketState) -> TicketState:
    started = time.perf_counter()
    safety_lang = "both"
    safety_result = draft_safety_check(state.draft_text or "", lang=safety_lang)
    updated = state.model_copy(
        update={
            "safety_result": safety_result,
            "status": TicketStatus.SAFETY_CHECKED,
            "updated_at": datetime.now(timezone.utc),
        }
    )

    ticket.safety_result = safety_result.model_dump(mode="json")
    ticket.status = TicketStatus.SAFETY_CHECKED.value
    ticket.workflow_stage = stage_for_status(TicketStatus.SAFETY_CHECKED).value

    write_audit_log(
        db=db,
        ticket_id=ticket.id,
        step_name=WorkflowStep.SAFETY_CHECK,
        input_json={"draft_text": state.draft_text, "lang": safety_lang},
        output_json={"step_status": "succeeded", **ticket.safety_result},
        duration_ms=_elapsed_ms(started),
    )
    return updated


def run_policy_aggregation_step(db: Session, ticket: Ticket, state: TicketState) -> TicketState:
    started = time.perf_counter()
    decision = aggregate_policy_decision(state)
    status = TicketStatus.CLOSED if decision.review_type.value == "no_impact_close" else TicketStatus.REVIEW_ROUTED
    updated = state.model_copy(
        update={
            "policy_decision": decision,
            "status": status,
            "updated_at": datetime.now(timezone.utc),
        }
    )

    ticket.policy_decision = decision.model_dump(mode="json")
    ticket.review_type = decision.review_type.value
    ticket.status = updated.status.value
    ticket.workflow_stage = stage_for_status(updated.status).value

    write_audit_log(
        db=db,
        ticket_id=ticket.id,
        step_name=WorkflowStep.POLICY_AGGREGATION,
        input_json={
            "matched": state.inventory_result.matched if state.inventory_result else None,
            "needs_identity_review": state.inventory_result.needs_identity_review if state.inventory_result else None,
            "evidence_status": state.sufficiency_check.evidence_status.value if state.sufficiency_check else None,
            "blocked_sentence_count": len(state.safety_result.blocked_sentences) if state.safety_result else 0,
        },
        output_json=policy_audit_output(state, decision, ticket.policy_decision),
        duration_ms=_elapsed_ms(started),
    )
    return updated


def normalize_inventory_match_payload(payload: dict) -> dict:
    normalized = {**payload}
    rows = []
    for row in normalized.get("matched_rows", []):
        normalized_row = {**row}
        if normalized_row.get("ndc") is not None:
            normalized_row["ndc"] = coerce_inventory_row_ndc(normalized_row["ndc"])
        rows.append(normalized_row)
    normalized["matched_rows"] = rows
    return normalized


def coerce_inventory_row_ndc(value) -> str:
    # Local handoff coercion only: inventory CSV may parse NDC as int/float.
    # Canonical event NDC normalization remains owned by app.event.normalizer.
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    digits = "".join(char for char in text if char.isdigit())
    if 0 < len(digits) < 11:
        return digits.zfill(11)
    return digits or text


def build_evidence_query(state: TicketState) -> str:
    event = state.event_normalized
    parts = [
        event.drug_name,
        event.event_type.value,
        event.classification.value if event.classification else "",
        event.recall_number,
        "evidence requirements and required actions",
    ]
    return " ".join(part for part in parts if part)


def evidence_audit_output(*, query: str, top_k: int, rag_result, evidence_result, sufficiency_check) -> dict:
    return {
        "step_status": "succeeded",
        "query": query,
        "top_k": top_k,
        "retrieval_context": retrieval_context_json(rag_result.context),
        "retrieval_plan": {
            "event_type": rag_result.plan.event_type,
            "targets": [target.to_dict() for target in rag_result.plan.targets],
        },
        "filter_expressions": sorted({chunk.filter_expr for chunk in rag_result.chunks if chunk.filter_expr}),
        "evidence_status": sufficiency_check.evidence_status.value,
        "coverage_score": sufficiency_check.coverage_score,
        "found_sources": [source.value for source in sufficiency_check.found_sources],
        "missing_sources": [source.value for source in sufficiency_check.missing_sources],
        "weak_sources": [source.value for source in sufficiency_check.weak_sources],
        "failure_reasons": sufficiency_check.failure_reasons,
        "chunk_count": len(evidence_result.top_chunks),
        "citations_ready": sufficiency_check.citations_ready,
        "retrieval_trace": rag_result.retrieval_trace,
        "evidence_result": evidence_result.model_dump(mode="json"),
        "sufficiency_check": sufficiency_check.model_dump(mode="json"),
    }


def retrieval_context_json(context: RetrievalContext) -> dict:
    return {
        "event_type": context.event_type,
        "query": context.query,
        "drug_name": context.drug_name,
        "normalized_drug_name": context.normalized_drug_name,
        "rxnorm_rxcui": context.rxnorm_rxcui,
        "ndc": context.ndc,
        "lot": context.lot,
        "recall_number": context.recall_number,
        "classification": context.classification,
        "target_profile": context.target_profile,
    }


def is_retryable_error(exc: Exception) -> bool:
    return not isinstance(exc, (ValueError, TypeError))


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
