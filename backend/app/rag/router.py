"""Evidence retrieval planning router.

This module owns the internal RAG planning contract: event type -> required
evidence document types and target sections. FastAPI endpoints for RAG/evidence
debugging live in app.rag.api.
"""

from __future__ import annotations

from app.rag.models import EvidencePlan, EvidenceTarget, RetrievalContext


class EvidenceRouter:
    def build_plan(self, context: RetrievalContext, *, top_k: int = 5) -> EvidencePlan:
        if context.target_profile == "recall_action":
            return EvidencePlan(
                event_type=context.event_type,
                targets=[
                    EvidenceTarget("recall_notice", sections=["recall_notice"], top_k=top_k),
                    EvidenceTarget("policy", sections=["required_actions"], top_k=top_k),
                    EvidenceTarget("sop", sections=["procedure"], top_k=top_k),
                ],
            )
        if context.target_profile == "label_safety":
            return EvidencePlan(
                event_type=context.event_type,
                targets=[
                    EvidenceTarget("label", sections=["warnings", "contraindications", "boxed_warning"], top_k=top_k),
                    EvidenceTarget("policy", sections=["review_routing_rules", "approval_requirements"], required=False, top_k=top_k),
                    EvidenceTarget("sop", sections=["safety_controls"], required=False, top_k=top_k),
                ],
            )
        if context.target_profile == "shortage_handling":
            return EvidencePlan(
                event_type=context.event_type,
                targets=[
                    EvidenceTarget("policy", sections=["required_actions", "escalation_criteria"], top_k=top_k),
                    EvidenceTarget("sop", sections=["procedure", "review_routing"], top_k=top_k),
                    EvidenceTarget("label", sections=["warnings", "contraindications", "drug_interactions"], required=False, top_k=top_k),
                ],
            )
        if context.target_profile == "workflow_explanation":
            ticket_specific_targets = []
            if context.event_type == "recall":
                ticket_specific_targets.append(
                    EvidenceTarget("recall_notice", sections=["recall_notice"], required=False, top_k=top_k)
                )
            elif context.event_type == "label_update":
                ticket_specific_targets.append(
                    EvidenceTarget("label", sections=["warnings", "contraindications", "boxed_warning"], required=False, top_k=top_k)
                )
            return EvidencePlan(
                event_type=context.event_type,
                targets=[
                    *ticket_specific_targets,
                    EvidenceTarget("policy", sections=["evidence_requirements", "review_routing_rules"], top_k=top_k),
                    EvidenceTarget("sop", sections=["evidence_requirements", "review_routing"], top_k=top_k),
                ],
            )

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
