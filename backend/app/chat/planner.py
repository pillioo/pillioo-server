from __future__ import annotations

from dataclasses import dataclass, field

from app.db.models.chat_model import ChatMessage
from app.schemas.workflow import TicketState


WORKFLOW_EXPLANATION = "workflow_explanation"
RECALL_ACTION = "recall_action"
LABEL_SAFETY = "label_safety"
SHORTAGE_HANDLING = "shortage_handling"
EVIDENCE_GAP = "evidence_gap"
GENERAL_TICKET_QUESTION = "general_ticket_question"

TICKET_STATE_ONLY = "ticket_state_only"
RETRIEVAL_REQUIRED = "retrieval_required"
HYBRID = "hybrid"


@dataclass(frozen=True)
class ChatPlan:
    intent: str
    standalone_query: str
    answer_mode: str
    target_profile: str
    retrieved_evidence_scope: str
    target_document_types: list[str] = field(default_factory=list)
    target_sections: list[str] = field(default_factory=list)


def build_chat_plan(
    *,
    user_query: str,
    recent_messages: list[ChatMessage],
    state: TicketState,
) -> ChatPlan:
    intent = classify_intent(user_query)
    answer_mode = answer_mode_for_intent(intent)
    target_profile = target_profile_for_intent(intent, state)
    return ChatPlan(
        intent=intent,
        standalone_query=build_standalone_query(
            user_query=user_query,
            recent_messages=recent_messages,
            state=state,
            intent=intent,
        ),
        answer_mode=answer_mode,
        target_profile=target_profile,
        retrieved_evidence_scope=retrieved_evidence_scope_for_profile(target_profile),
        target_document_types=target_document_types_for_profile(target_profile),
        target_sections=target_sections_for_profile(target_profile),
    )


def classify_intent(user_query: str) -> str:
    query = user_query.casefold()

    if _contains_any(query, ["부족", "missing", "weak", "sufficient", "insufficient", "evidence gap", "근거 부족"]):
        return EVIDENCE_GAP
    if _contains_any(query, ["왜", "why", "review", "routed", "route", "routing", "검토", "리뷰"]):
        return WORKFLOW_EXPLANATION
    if _contains_any(query, ["투여", "위험", "warning", "warnings", "contraindication", "boxed", "safety", "안전"]):
        return LABEL_SAFETY
    if _contains_any(query, ["대체", "대체약", "shortage", "substitute", "substitution", "부족", "품절"]):
        return SHORTAGE_HANDLING
    if _contains_any(query, ["조치", "격리", "보관", "회수", "quarantine", "hold", "recall", "required action", "procedure"]):
        return RECALL_ACTION
    return GENERAL_TICKET_QUESTION


def answer_mode_for_intent(intent: str) -> str:
    if intent == EVIDENCE_GAP:
        return TICKET_STATE_ONLY
    if intent == WORKFLOW_EXPLANATION:
        return HYBRID
    if intent in {RECALL_ACTION, LABEL_SAFETY, SHORTAGE_HANDLING}:
        return RETRIEVAL_REQUIRED
    return HYBRID


def target_profile_for_intent(intent: str, state: TicketState) -> str:
    if intent == RECALL_ACTION:
        return "recall_action"
    if intent == LABEL_SAFETY:
        return "label_safety"
    if intent == SHORTAGE_HANDLING:
        return "shortage_handling"
    if intent == WORKFLOW_EXPLANATION:
        return "workflow_explanation"
    if intent == EVIDENCE_GAP:
        return "evidence_gap"
    if state.event_type:
        return f"{state.event_type.value}_general"
    return "general"


def build_standalone_query(
    *,
    user_query: str,
    recent_messages: list[ChatMessage],
    state: TicketState,
    intent: str,
) -> str:
    event = state.event_normalized
    context_terms = [
        state.event_type.value if state.event_type else None,
        event.drug_name if event else None,
        event.recall_number if event and not event.recall_number_is_fallback else None,
        event.ndc if event else None,
        event.lot if event else None,
        state.classification.value if state.classification else None,
    ]
    topic = _recent_user_topic(recent_messages)
    intent_terms = {
        RECALL_ACTION: "required actions quarantine storage recall procedure",
        LABEL_SAFETY: "label safety warnings contraindications boxed warning administration risk",
        SHORTAGE_HANDLING: "shortage substitution alternative escalation procedure",
        WORKFLOW_EXPLANATION: "workflow routing review decision evidence sufficiency",
        EVIDENCE_GAP: "evidence sufficiency missing weak sources citations",
    }.get(intent)

    parts = [term for term in context_terms if term]
    if topic:
        parts.append(topic)
    if intent_terms:
        parts.append(intent_terms)
    parts.append(user_query.strip())
    return _dedupe_words(" ".join(parts))


def target_document_types_for_profile(target_profile: str) -> list[str]:
    return {
        "recall_action": ["recall_notice", "policy", "sop"],
        "label_safety": ["label", "policy", "sop"],
        "shortage_handling": ["policy", "sop", "label"],
        "workflow_explanation": ["recall_notice", "label", "policy", "sop"],
        "evidence_gap": [],
    }.get(target_profile, [])


def target_sections_for_profile(target_profile: str) -> list[str]:
    return {
        "recall_action": ["recall_notice", "required_actions", "procedure"],
        "label_safety": ["warnings", "contraindications", "boxed_warning", "safety_controls"],
        "shortage_handling": ["required_actions", "procedure", "escalation_criteria", "drug_interactions"],
        "workflow_explanation": ["recall_notice", "warnings", "review_routing_rules", "review_routing", "evidence_requirements"],
        "evidence_gap": [],
    }.get(target_profile, [])


def retrieved_evidence_scope_for_profile(target_profile: str) -> str:
    return {
        "recall_action": "recall_action",
        "label_safety": "label_safety",
        "shortage_handling": "shortage_handling",
        "workflow_explanation": "workflow_routing_and_ticket_evidence",
        "evidence_gap": "ticket_state",
    }.get(target_profile, "general_ticket_evidence")


def _recent_user_topic(recent_messages: list[ChatMessage]) -> str | None:
    for message in reversed(recent_messages):
        if message.role == "user" and message.content:
            content = message.content.strip()
            if content:
                return content[:160]
    return None


def _contains_any(value: str, needles: list[str]) -> bool:
    return any(needle in value for needle in needles)


def _dedupe_words(value: str) -> str:
    seen: set[str] = set()
    words: list[str] = []
    for word in value.split():
        key = word.casefold()
        if key in seen:
            continue
        seen.add(key)
        words.append(word)
    return " ".join(words)
