from __future__ import annotations

from app.rag.models import EvidencePlan, EvidenceTarget, RetrievalContext


class EvidenceRouter:
    def build_plan(self, context: RetrievalContext, *, top_k: int = 5) -> EvidencePlan:
        event_type = context.event_type
        if event_type == "recall":
            targets = [
                EvidenceTarget("recall_notice", sections=["recall_notice"], top_k=top_k),
                EvidenceTarget(
                    "policy",
                    sections=["evidence_requirements", "required_actions", "review_routing_rules", "escalation_criteria"],
                    top_k=top_k,
                ),
                EvidenceTarget("sop", sections=["evidence_requirements", "procedure", "review_routing", "safety_controls"], top_k=top_k),
            ]
        elif event_type == "label_update":
            targets = [
                EvidenceTarget("label", sections=["warnings", "contraindications", "boxed_warning", "dosage_and_administration"], top_k=top_k),
                EvidenceTarget("policy", sections=["evidence_requirements", "review_routing_rules", "approval_requirements"], top_k=top_k),
                EvidenceTarget("sop", sections=["evidence_requirements", "procedure", "review_routing"], top_k=top_k),
            ]
        elif event_type == "shortage":
            # label is best-effort context; policy + sop alone is sufficient evidence.
            targets = [
                EvidenceTarget("policy", sections=["evidence_requirements", "required_actions", "review_routing_rules"], top_k=top_k),
                EvidenceTarget("sop", sections=["evidence_requirements", "procedure", "review_routing"], top_k=top_k),
                EvidenceTarget("label", sections=["warnings", "contraindications", "drug_interactions"], required=False, top_k=top_k),
            ]
        else:
            targets = [
                EvidenceTarget("recall_notice", sections=["recall_notice"], required=False, top_k=top_k),
                EvidenceTarget("label", required=False, top_k=top_k),
                EvidenceTarget("policy", required=False, top_k=top_k),
                EvidenceTarget("sop", required=False, top_k=top_k),
            ]

        return EvidencePlan(event_type=event_type, targets=targets)
