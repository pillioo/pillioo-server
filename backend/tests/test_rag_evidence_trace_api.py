from __future__ import annotations

from app.db.models.ticket import Ticket
from app.rag.evidence_trace import build_ticket_evidence_trace


def ticket() -> Ticket:
    item = Ticket(
        ticket_id="T-2026-0001",
        status="REVIEW_ROUTED",
        workflow_stage="PENDING_REVIEW",
        event_type="recall",
        drug_name="midazolam",
        ndc="00641601441",
        classification="class_i",
    )
    item.id = 1
    item.review_type = "evidence_review"
    item.evidence_result = {
        "top_chunks": [
            {
                "document_type": "policy",
                "section": "required_actions",
                "source_path": "policy.md",
            }
        ],
        "citations": [{"source": "policy.md", "section": "required_actions", "score": 0.91}],
    }
    item.sufficiency_check = {
        "required_sources": ["recall_notice", "policy", "sop"],
        "found_sources": ["recall_notice", "policy"],
        "missing_sources": ["sop"],
        "weak_sources": [],
        "failure_reasons": [{"reason": "missing_required_document_type", "document_type": "sop"}],
        "coverage_score": 0.67,
        "evidence_status": "insufficient",
        "citations_ready": True,
    }
    return item


def test_build_ticket_evidence_trace_combines_ticket_evidence_and_audit_trace() -> None:
    payload = build_ticket_evidence_trace(
        ticket(),
        evidence_audit_output={
            "query": "midazolam recall evidence requirements",
            "top_k": 5,
            "retrieval_context": {"event_type": "recall"},
            "filter_expressions": ['document_type == "policy"'],
            "retrieval_trace": {
                "counts": {"selected_chunks": 2},
                "filter_attempts": [{"level": "section", "hit_count": 2}],
            },
        },
        gate_audit_output={
            "gate_status": "blocked",
            "can_generate_draft": False,
            "skip_reason": "insufficient_evidence",
        },
        policy_audit_output={
            "review_type": "evidence_review",
            "final_routing_reason": "Evidence gate blocked draft generation: missing_required_document_type.",
            "reasons": ["Evidence gate blocked draft generation: missing_required_document_type."],
        },
        warnings=[{"source": "audit_log", "step_name": "sufficiency_check", "message": "fallback"}],
    )

    assert payload["ticket_id"] == "T-2026-0001"
    assert payload["evidence_status"] == "insufficient"
    assert payload["missing_sources"] == ["sop"]
    assert payload["failure_reasons"] == [{"reason": "missing_required_document_type", "document_type": "sop"}]
    assert payload["gate"] == {
        "gate_status": "blocked",
        "can_generate_draft": False,
        "skip_reason": "insufficient_evidence",
    }
    assert payload["routing"]["review_type"] == "evidence_review"
    assert payload["warnings"] == [{"source": "audit_log", "step_name": "sufficiency_check", "message": "fallback"}]
    assert payload["retrieval"]["query"] == "midazolam recall evidence requirements"
    assert payload["retrieval"]["trace"]["counts"]["selected_chunks"] == 2
    assert payload["top_chunks"][0]["section"] == "required_actions"


def test_build_ticket_evidence_trace_handles_missing_audit_logs() -> None:
    payload = build_ticket_evidence_trace(ticket())

    assert payload["retrieval"]["trace"] == {}
    assert payload["warnings"] == []
    assert payload["gate"]["gate_status"] is None
    assert payload["routing"]["review_type"] == "evidence_review"
