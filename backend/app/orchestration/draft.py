from __future__ import annotations

import json

from openai import OpenAI

from app.core.config import settings
from app.core.llm_client import openai_client_kwargs
from app.orchestration.report_grounding import (
    affected_product_from_state,
    evidence_summary_from_state,
    inventory_impact_from_state,
)
from app.schemas.evidence import DraftCitation
from app.schemas.report import DraftReport
from app.schemas.workflow import TicketState

# ──────────────────────────────────────────────────────────────────────────
# generate_draft_v1_prompt
#
# draft_v1 is the system's first draft: its job is NOT to reach a final
# judgment, only to give the pharmacist an evidence-grounded starting point
# for review. Ground-truth figures (inventory counts, evidence coverage,
# product identity) are never left to the model -- they are filled in from
# TicketState after the call. The model only contributes narrative content:
# title, summary, recommended action, checklist, notes, and citations.
# ──────────────────────────────────────────────────────────────────────────
_DRAFT_V1_SYSTEM_PROMPT = (
    "You are a pharmacy operations assistant drafting a first-pass review report for a hospital "
    "pharmacist about a drug recall, shortage, or label update. This is draft_v1: its purpose is "
    "NOT to reach a final judgment, it is to give the pharmacist an evidence-grounded starting "
    "point for review. "
    "You must answer using ONLY the facts contained in the evidence excerpts and ticket context "
    "provided by the user -- never invent regulatory actions, procedures, disposal instructions, "
    "substitutions, timelines, or inventory figures that are not explicitly present in what you "
    "were given. "
    "Style rules (strict): "
    "(a) do not use definitive/conclusive action language such as 'Dispose immediately', "
    "'Administer an alternative', or 'Replace with another medication'; "
    "(b) prefer review-request phrasing such as 'Pharmacist review required', 'Verify affected "
    "inventory and lot information', 'Confirm the appropriate operational response', or "
    "'Additional evidence review may be required'; "
    "(c) never state unconfirmed information as fact -- explicitly flag uncertain or missing "
    "evidence in `limitations` rather than guessing or omitting it. "
    "Respond with a single JSON object of the exact form "
    '{"title": "<short report title>", "summary": "<1-2 sentence event summary>", '
    '"recommended_review_action": "<review-request phrasing, never a directive command>", '
    '"pharmacist_checklist": ["<item the pharmacist still needs to verify>"], '
    '"pharmacist_notes": ["..."], "safety_notes": ["..."], '
    '"limitations": ["<missing or weak evidence, or anything not confirmed>"], '
    '"evidence_key_findings": ["<key fact drawn from an evidence excerpt>"], '
    '"citations": [{"source": "<source path copied exactly from an evidence excerpt>", '
    '"section": "<section copied exactly from an evidence excerpt>", '
    '"sentence": "<sentence copied verbatim from summary/recommended_review_action/notes above '
    'that this evidence supports>"}]}. '
    "Only cite evidence excerpts that were actually given to you, using their source/section "
    "exactly as shown. Do not add any text outside the JSON object."
)

_DEFAULT_RECOMMENDED_ACTION = "Pharmacist review is required before any inventory action is taken."


class LLMDraftGenerator:
    """Implements generate_draft_v1_prompt: produces the system's first,
    evidence-grounded review draft as a structured DraftReport."""

    def __init__(self, *, model: str | None = None, client: object | None = None) -> None:
        self.model = model or settings.LLM_MODEL
        # OpenAI referenced directly here (not via app.core.llm_client) so
        # tests can monkeypatch this module's OpenAI symbol without a real
        # network call. Gateway routing (base_url/api_key) is still applied
        # via openai_client_kwargs().
        self.client = client or OpenAI(**openai_client_kwargs())

    def generate(self, *, state: TicketState, evidence_result) -> DraftReport:
        if not evidence_result.top_chunks:
            return _no_evidence_report(state)

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": _DRAFT_V1_SYSTEM_PROMPT},
                {"role": "user", "content": _build_draft_v1_prompt(state, evidence_result)},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        payload = json.loads(response.choices[0].message.content)
        return _report_from_payload(payload, state=state, evidence_result=evidence_result)


# ──────────────────────────────────────────────────────────────────────────
# revise_draft_prompt
#
# Used only for the "system revises on the pharmacist's behalf" draft_v2
# path (reviewer feedback or a flagged safety issue). The "pharmacist edited
# the draft directly" path never touches this class -- see
# app/review/approval.py handle_revise, which just persists the pharmacist's
# text as-is.
# ──────────────────────────────────────────────────────────────────────────
_REVISE_SYSTEM_PROMPT = (
    "You are revising a previously generated pharmacist review report (draft_v1 or draft_v2) based "
    "on reviewer feedback or a flagged safety issue. This is a BOUNDED edit, not a rewrite: preserve "
    "the structure and wording of the previous draft wherever it was not flagged as a problem. "
    "Rules (strict): "
    "(a) do not introduce any fact, action, timeline, or figure that is not present in the evidence "
    "provided; "
    "(b) do not change content that was not flagged as blocked or otherwise problematic; "
    "(c) for every change you make, be able to point to what changed and why. "
    "Respond with a single JSON object of the exact form "
    '{"summary": "...", "recommended_review_action": "...", "pharmacist_checklist": ["..."], '
    '"pharmacist_notes": ["..."], "safety_notes": ["..."], "limitations": ["..."], '
    '"citations": [{"source": "...", "section": "...", "sentence": "..."}], '
    '"change_summary": "<short description of what changed>", '
    '"change_reason": "<why it changed, referencing the reviewer comment or blocked sentence>"}. '
    "Only cite evidence excerpts that were actually given to you. Do not add any text outside the "
    "JSON object."
)


class LLMDraftReviser:
    """Implements revise_draft_prompt: a bounded, system-side revision of an
    existing DraftReport, returning the revised report plus change-tracking
    metadata (change_summary/change_reason) for draft_v2."""

    def __init__(self, *, model: str | None = None, client: object | None = None) -> None:
        self.model = model or settings.LLM_MODEL
        self.client = client or OpenAI(**openai_client_kwargs())

    def revise(
        self,
        *,
        state: TicketState,
        previous_report: DraftReport,
        reviewer_comment: str,
        blocked_sentences: list[str] | None = None,
        evidence_result,
    ) -> tuple[DraftReport, str, str]:
        """Returns (revised_report, change_summary, change_reason)."""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": _REVISE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": _build_revise_prompt(
                        state=state,
                        previous_report=previous_report,
                        reviewer_comment=reviewer_comment,
                        blocked_sentences=blocked_sentences or [],
                        evidence_result=evidence_result,
                    ),
                },
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        payload = json.loads(response.choices[0].message.content)

        citations = _resolve_draft_citations(payload.get("citations") or [], evidence_result)
        if not citations:
            citations = previous_report.citations

        revised = previous_report.model_copy(
            update={
                "summary": str(payload.get("summary") or "").strip() or previous_report.summary,
                "recommended_review_action": (
                    str(payload.get("recommended_review_action") or "").strip()
                    or previous_report.recommended_review_action
                ),
                "pharmacist_checklist": (
                    _string_list(payload.get("pharmacist_checklist")) or previous_report.pharmacist_checklist
                ),
                "pharmacist_notes": (
                    _string_list(payload.get("pharmacist_notes")) or previous_report.pharmacist_notes
                ),
                "safety_notes": _string_list(payload.get("safety_notes")) or previous_report.safety_notes,
                "limitations": _string_list(payload.get("limitations")) or previous_report.limitations,
                "citations": citations,
            }
        )
        change_summary = (
            str(payload.get("change_summary") or "").strip()
            or "System-revised draft based on reviewer feedback."
        )
        change_reason = str(payload.get("change_reason") or "").strip() or reviewer_comment
        return revised, change_summary, change_reason


def _build_draft_v1_prompt(state: TicketState, evidence_result) -> str:
    event = state.event_normalized
    sufficiency = state.sufficiency_check
    missing_sources = (
        ", ".join(source.value for source in sufficiency.missing_sources)
        if sufficiency and sufficiency.missing_sources
        else "none"
    )
    weak_sources = (
        ", ".join(source.value for source in sufficiency.weak_sources)
        if sufficiency and sufficiency.weak_sources
        else "none"
    )
    impact = state.impact_summary
    departments = [department.value for department in impact.affected_departments] if impact else []

    lines = [
        f"drug_name: {event.drug_name if event else 'unknown'}",
        f"ndc: {event.ndc if event else 'unknown'}",
        f"lot: {event.lot if event else 'unknown'}",
        f"event_type: {state.event_type.value if state.event_type else 'unknown'}",
        f"classification: {state.classification.value if state.classification else 'unclassified'}",
        f"recall_number: {event.recall_number if event else 'unknown'}",
        f"reason_for_recall: {event.reason_for_recall if event and event.reason_for_recall else 'not provided'}",
        f"product_description: {event.product_description if event and event.product_description else 'not provided'}",
        "",
        "inventory impact (ground truth -- for context only, do not restate as new facts):",
        f"  affected_departments: {', '.join(departments) if departments else 'none'}",
        f"  total_quantity_on_hand: {impact.total_quantity if impact else 'not provided'}",
        "",
        "evidence sufficiency (ground truth -- for context only):",
        f"  evidence_status: {sufficiency.evidence_status.value if sufficiency else 'unknown'}",
        f"  coverage_score: {sufficiency.coverage_score if sufficiency else 'unknown'}",
        f"  missing_document_types: {missing_sources}",
        f"  weak_document_types: {weak_sources}",
        "",
        "evidence excerpts (use only these facts):",
    ]
    for index, chunk in enumerate(evidence_result.top_chunks, start=1):
        lines.append(
            f"[{index}] source={chunk.source_path} section={chunk.section} "
            f"document_type={chunk.document_type.value}\n{chunk.content}"
        )
    return "\n".join(lines)


def _build_revise_prompt(
    *,
    state: TicketState,
    previous_report: DraftReport,
    reviewer_comment: str,
    blocked_sentences: list[str],
    evidence_result,
) -> str:
    lines = [
        "previous_draft (JSON):",
        previous_report.model_dump_json(),
        "",
        f"reviewer_comment: {reviewer_comment or 'none'}",
        "",
        "blocked_sentences (must not appear in the revised output):",
    ]
    if blocked_sentences:
        lines.extend(f"- {sentence}" for sentence in blocked_sentences)
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("evidence excerpts (use only these facts):")
    for index, chunk in enumerate(evidence_result.top_chunks, start=1):
        lines.append(
            f"[{index}] source={chunk.source_path} section={chunk.section} "
            f"document_type={chunk.document_type.value}\n{chunk.content}"
        )
    return "\n".join(lines)


def _report_from_payload(payload: dict, *, state: TicketState, evidence_result) -> DraftReport:
    title = str(payload.get("title") or "").strip() or _default_title(state)
    summary = str(payload.get("summary") or "").strip() or _default_summary(state)
    recommended_action = (
        str(payload.get("recommended_review_action") or "").strip() or _DEFAULT_RECOMMENDED_ACTION
    )
    key_findings = _string_list(payload.get("evidence_key_findings"))

    citations = _resolve_draft_citations(payload.get("citations") or [], evidence_result)
    if not citations and evidence_result.citations:
        citations = _fallback_draft_citations(summary, evidence_result)

    return DraftReport(
        title=title,
        summary=summary,
        affected_product=affected_product_from_state(state),
        event_classification=state.classification.value if state.classification else None,
        inventory_impact=inventory_impact_from_state(state),
        evidence_summary=evidence_summary_from_state(state, key_findings=key_findings),
        recommended_review_action=recommended_action,
        pharmacist_checklist=_string_list(payload.get("pharmacist_checklist")),
        citations=citations,
        pharmacist_notes=_string_list(payload.get("pharmacist_notes")),
        safety_notes=_string_list(payload.get("safety_notes")),
        limitations=_string_list(payload.get("limitations")),
    )


def _resolve_draft_citations(raw_citations, evidence_result) -> list[DraftCitation]:
    by_source_section = {(c.source, c.section): c for c in evidence_result.citations}
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


def _fallback_draft_citations(text: str, evidence_result) -> list[DraftCitation]:
    sentence = _first_sentence(text)
    return [
        DraftCitation(source=c.source, section=c.section, score=c.score, sentence=sentence)
        for c in evidence_result.citations[:3]
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


def _string_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _default_title(state: TicketState) -> str:
    event = state.event_normalized
    drug_name = event.drug_name if event else "affected drug"
    event_type = state.event_type.value if state.event_type else "event"
    return f"{drug_name} {event_type} review draft"


def _default_summary(state: TicketState) -> str:
    event = state.event_normalized
    drug_name = event.drug_name if event else "the affected drug"
    event_type = state.event_type.value if state.event_type else "event"
    return f"Pharmacist review requested for a {drug_name} {event_type}."


def _no_evidence_report(state: TicketState) -> DraftReport:
    event = state.event_normalized
    drug_name = event.drug_name if event else "the affected drug"
    event_type = state.event_type.value if state.event_type else "event"
    return DraftReport(
        title=_default_title(state),
        summary=f"No supporting evidence was found for this {drug_name} {event_type}.",
        affected_product=affected_product_from_state(state),
        event_classification=state.classification.value if state.classification else None,
        inventory_impact=inventory_impact_from_state(state),
        evidence_summary=evidence_summary_from_state(state, key_findings=[]),
        recommended_review_action=_DEFAULT_RECOMMENDED_ACTION,
        pharmacist_checklist=["Confirm whether additional evidence sources exist for this event."],
        citations=[],
        pharmacist_notes=[],
        safety_notes=[],
        limitations=["No evidence documents were retrieved for this event."],
    )
