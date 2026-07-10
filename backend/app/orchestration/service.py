from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from openai import OpenAI
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.ticket import Ticket
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
    ) -> tuple[str, list[DraftCitation]]:
        ...


@dataclass(frozen=True)
class OrchestrationResult:
    ticket: Ticket
    state: TicketState
    created: bool = True


class SimpleDraftGenerator:
    def generate(
        self,
        *,
        state: TicketState,
        evidence_result: EvidenceResult,
    ) -> tuple[str, list[DraftCitation]]:
        drug_name = state.event_normalized.drug_name if state.event_normalized else "the affected drug"
        classification = state.classification.value if state.classification else "unclassified"
        departments = []
        if state.impact_summary:
            departments = [department.value for department in state.impact_summary.affected_departments]
        department_text = ", ".join(departments) if departments else "no affected departments"

        draft_text = (
            f"{drug_name} {classification} {state.event_type.value} notice. "
            f"Affected departments: {department_text}. "
            "Hold affected inventory for pharmacist review before further action."
        )

        citations = [
            DraftCitation(
                source=citation.source,
                section=citation.section,
                score=citation.score,
                sentence="Hold affected inventory for pharmacist review before further action.",
            )
            for citation in evidence_result.citations[:3]
        ]
        return draft_text, citations


_DRAFT_SYSTEM_PROMPT = (
    "You are a pharmacy operations assistant drafting an internal notice for hospital "
    "pharmacists about a drug recall, shortage, or label update. "
    "You must answer using ONLY the facts contained in the evidence excerpts provided by "
    "the user -- never invent regulatory actions, procedures, disposal instructions, "
    "substitutions, or timelines that are not explicitly present in the evidence. "
    "If the evidence does not specify a required action, say that pharmacist review is "
    "required instead of guessing. Write 2-5 short, conservative, factual sentences. "
    "Respond with a single JSON object of the exact form "
    '{"draft_text": "<the full draft notice>", "citations": '
    '[{"source": "<source path copied exactly from an evidence excerpt>", '
    '"section": "<section copied exactly from an evidence excerpt>", '
    '"sentence": "<sentence copied verbatim from draft_text that this evidence supports>"}]}. '
    "Only cite evidence excerpts that were actually given to you, using their source/section "
    "exactly as shown. Do not add any text outside the JSON object."
)


class LLMDraftGenerator:
    """DraftGenerator backed by an LLM chat completion.

    Mirrors the OpenAI client usage pattern of OpenAIQueryEmbedder
    (app/rag/service.py): the model name is read from app.core.config.settings,
    and a plain `OpenAI()` client is used. A `client` override is accepted so
    tests can inject a fake/stub client without touching global state.

    Output is grounded strictly in evidence_result.top_chunks -- the prompt
    instructs the model to answer only from the given excerpts. Citation
    scores are never taken from the model; they are always resolved back
    against evidence_result.citations so a hallucinated source/section is
    simply dropped rather than trusted.
    """

    def __init__(self, *, model: str | None = None, client: object | None = None) -> None:
        self.model = model or settings.LLM_MODEL
        self.client = client or OpenAI()

    def generate(
        self,
        *,
        state: TicketState,
        evidence_result: EvidenceResult,
    ) -> tuple[str, list[DraftCitation]]:
        if not evidence_result.top_chunks:
            # Nothing to ground a draft on -- do not call the model, and do not
            # fabricate citations for evidence that does not exist.
            return _no_evidence_draft_text(state), []

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": _DRAFT_SYSTEM_PROMPT},
                {"role": "user", "content": _build_draft_prompt(state, evidence_result)},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        payload = json.loads(response.choices[0].message.content)

        draft_text = str(payload.get("draft_text") or "").strip() or _no_evidence_draft_text(state)
        citations = _resolve_draft_citations(payload.get("citations") or [], evidence_result)
        if not citations and evidence_result.citations:
            # The model produced no (valid) citations even though evidence exists.
            # Fall back to attaching the top evidence, rather than shipping an
            # ungrounded draft with zero citations.
            citations = _fallback_draft_citations(draft_text, evidence_result)
        return draft_text, citations


def _build_draft_prompt(state: TicketState, evidence_result: EvidenceResult) -> str:
    event = state.event_normalized
    departments = (
        [department.value for department in state.impact_summary.affected_departments]
        if state.impact_summary
        else []
    )
    lines = [
        f"drug_name: {event.drug_name if event else 'unknown'}",
        f"event_type: {state.event_type.value if state.event_type else 'unknown'}",
        f"classification: {state.classification.value if state.classification else 'unclassified'}",
        f"recall_number: {event.recall_number if event else 'unknown'}",
        f"reason_for_recall: {event.reason_for_recall if event and event.reason_for_recall else 'not provided'}",
        f"product_description: {event.product_description if event and event.product_description else 'not provided'}",
        f"affected_departments: {', '.join(departments) if departments else 'none'}",
        "",
        "evidence excerpts (use only these facts):",
    ]
    for index, chunk in enumerate(evidence_result.top_chunks, start=1):
        lines.append(
            f"[{index}] source={chunk.source_path} section={chunk.section} "
            f"document_type={chunk.document_type.value}\n{chunk.content}"
        )
    return "\n".join(lines)


def _resolve_draft_citations(raw_citations: list, evidence_result: EvidenceResult) -> list[DraftCitation]:
    by_source_section = {(citation.source, citation.section): citation for citation in evidence_result.citations}
    resolved: list[DraftCitation] = []
    for item in raw_citations:
        if not isinstance(item, dict):
            continue
        sentence = item.get("sentence")
        matched = by_source_section.get((item.get("source"), item.get("section")))
        if not matched or not sentence:
            continue
        resolved.append(
            DraftCitation(
                source=matched.source,
                section=matched.section,
                score=matched.score,
                sentence=str(sentence).strip(),
            )
        )
    return resolved


def _fallback_draft_citations(draft_text: str, evidence_result: EvidenceResult) -> list[DraftCitation]:
    sentence = _first_sentence(draft_text)
    return [
        DraftCitation(source=citation.source, section=citation.section, score=citation.score, sentence=sentence)
        for citation in evidence_result.citations[:3]
    ]


def _first_sentence(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return "Please consult the pharmacist before taking action."
    for separator in (". ", "\n"):
        if separator in stripped:
            head = stripped.split(separator)[0].strip()
            return head if head.endswith((".", "!", "?")) else f"{head}."
    return stripped


def _no_evidence_draft_text(state: TicketState) -> str:
    drug_name = state.event_normalized.drug_name if state.event_normalized else "the affected drug"
    event_type = state.event_type.value if state.event_type else "event"
    return (
        f"No supporting evidence was found for this {drug_name} {event_type}. "
        "Please consult the pharmacist before taking action."
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
