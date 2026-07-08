"""
Shared enums for workflow schemas.

Use enums for closed values that drive branching logic.
Open-ended values, such as document sections, should remain strings.
"""

from enum import Enum


class EventType(str, Enum):
    RECALL = "recall"
    SHORTAGE = "shortage"
    LABEL_UPDATE = "label_update"


class Classification(str, Enum):
    CLASS_I = "class_i"
    CLASS_II = "class_ii"
    CLASS_III = "class_iii"


class TicketStatus(str, Enum):
    CREATED = "CREATED"
    INVENTORY_CHECKED = "INVENTORY_CHECKED"
    EVIDENCE_RETRIEVED = "EVIDENCE_RETRIEVED"
    DRAFT_GENERATED = "DRAFT_GENERATED"
    SAFETY_CHECKED = "SAFETY_CHECKED"
    REVIEW_ROUTED = "REVIEW_ROUTED"
    # Distinguishes retryable execution failures from normal HITL routing.
    WORKFLOW_FAILED = "WORKFLOW_FAILED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CLOSED = "CLOSED"


class Department(str, Enum):
    ICU = "ICU"
    ER = "ER"
    OR = "OR"
    GW = "GW"


class Priority(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class MatchType(str, Enum):
    EXACT_NDC_MATCH = "exact_ndc_match"
    FUZZY_NAME_MATCH = "fuzzy_name_match"
    NO_MATCH = "no_match"


class DocumentType(str, Enum):
    POLICY = "policy"
    SOP = "sop"
    RECALL_NOTICE = "recall_notice"
    LABEL = "label"


class EvidenceStatus(str, Enum):
    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"


class ReviewType(str, Enum):
    IDENTITY_REVIEW = "identity_review"
    EVIDENCE_REVIEW = "evidence_review"
    ACTION_REVIEW = "action_review"
    FINAL_APPROVAL = "final_approval"
    NO_IMPACT_CLOSE = "no_impact_close"


class PolicyDecisionAction(str, Enum):
    CLOSE = "close"
    ROUTE_TO_HITL = "route_to_hitl"
    REQUEST_FINAL_APPROVAL = "request_final_approval"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    # Schema-aligned only; a follow-up should decide whether handle_revise
    # should persist Approval.status = REVISED.
    REVISED = "revised"


class BlockedCategory(str, Enum):
    DIRECT_MEDICAL_INSTRUCTION = "direct_medical_instruction"
    SUBSTITUTION_RECOMMENDATION = "substitution_recommendation"
    DISPOSAL_INSTRUCTION = "disposal_instruction"
    CERTAINTY_WITHOUT_APPROVAL = "certainty_without_approval"


class ReportVersionTag(str, Enum):
    DRAFT_V1 = "draft_v1"
    DRAFT_V2 = "draft_v2"
    FINAL_V1 = "final_v1"


class WorkflowStep(str, Enum):
    EVENT_NORMALIZED = "event_normalized"
    TICKET_CREATED = "ticket_created"
    INVENTORY_MATCH = "inventory_match"
    IMPACT_ASSESSMENT = "impact_assessment"
    EVIDENCE_ROUTING = "evidence_routing"
    EVIDENCE_RETRIEVAL = "evidence_retrieval"
    SUFFICIENCY_CHECK = "sufficiency_check"
    DRAFT_GENERATION = "draft_generation"
    SAFETY_CHECK = "safety_check"
    INVENTORY_QUALITY_CHECK = "inventory_quality_check"
    RAG_QUALITY_CHECK = "rag_quality_check"
    POLICY_AGGREGATION = "policy_aggregation"
    HITL_ROUTED = "hitl_routed"
    APPROVAL_DECISION = "approval_decision"


EVENT_TYPE_DOCUMENT_TYPES: dict[EventType, list[DocumentType]] = {
    EventType.RECALL: [
        DocumentType.POLICY,
        DocumentType.SOP,
        DocumentType.RECALL_NOTICE,
    ],
    EventType.SHORTAGE: [
        DocumentType.POLICY,
        DocumentType.SOP,
    ],
    EventType.LABEL_UPDATE: [
        DocumentType.LABEL,
    ],
}
