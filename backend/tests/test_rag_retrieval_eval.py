from __future__ import annotations

from app.rag.models import RetrievalContext, SufficiencyResult
from scripts.rag.eval.run_retrieval_eval import (
    GoldenQuery,
    build_retrieval_context,
    context_from_expected,
    dedupe_hits,
    evaluate_empty_hits,
    evaluate_hit_set,
    evaluate_hits,
    evaluate_sufficiency,
    matches_expected,
    summarize_results,
)


def sufficiency_result(**overrides: object) -> SufficiencyResult:
    defaults = {
        "required_document_types": ["policy", "sop"],
        "found_document_types": ["policy"],
        "missing_document_types": ["sop"],
        "weak_document_types": [],
        "coverage_score": 0.5,
        "evidence_status": "insufficient",
        "needs_evidence_review": True,
        "citations_ready": True,
    }
    defaults.update(overrides)
    return SufficiencyResult(**defaults)


def golden_query(**overrides: object) -> GoldenQuery:
    defaults = {
        "id": "case",
        "query": "q",
        "top_k": 5,
        "filter": "",
        "context": {},
        "expected": {},
    }
    defaults.update(overrides)
    return GoldenQuery(**defaults)


def test_matches_expected_supports_content_contains_and_any_section() -> None:
    hit = {
        "document_type": "recall_notice",
        "event_type": "recall",
        "section": "recall_notice",
        "recall_number": "D-0277-2024",
        "content": "Reason for recall: Superpotent drug product.",
    }

    assert matches_expected(
        hit,
        {
            "document_type": "recall_notice",
            "event_type": "recall",
            "recall_number": "D-0277-2024",
            "any_section": ["recall_notice", "reason_for_recall"],
            "content_contains": ["superpotent", "drug"],
        },
    )


def test_evaluate_hits_returns_first_matching_rank() -> None:
    hits = [
        {"chunk_id": "wrong", "document_type": "label", "score": 0.9},
        {"chunk_id": "right", "document_type": "policy", "score": 0.8},
    ]

    result = evaluate_hits(hits, {"document_type": "policy"})

    assert result["passed"] is True
    assert result["rank"] == 2
    assert result["top_chunk_id"] == "wrong"
    assert result["top_score"] == 0.9
    assert result["failures"] == []


def test_evaluate_hits_reports_failure_without_match() -> None:
    result = evaluate_hits(
        [{"chunk_id": "wrong", "document_type": "label", "score": 0.7}],
        {"document_type": "recall_notice"},
    )

    assert result["passed"] is False
    assert result["rank"] is None
    assert result["top_chunk_id"] == "wrong"
    assert result["failures"] == ["no hit matched expected.any_hit"]


def test_dedupe_hits_keeps_first_hit_for_repeated_field() -> None:
    hits = [
        {"chunk_id": "first", "content_hash": "same", "score": 0.9},
        {"chunk_id": "duplicate", "content_hash": "same", "score": 0.8},
        {"chunk_id": "second", "content_hash": "other", "score": 0.7},
        {"chunk_id": "missing_hash", "score": 0.6},
    ]

    deduped = dedupe_hits(hits, "content_hash")

    assert [hit["chunk_id"] for hit in deduped] == ["first", "second", "missing_hash"]


def test_evaluate_hits_supports_nested_any_hit_and_set_expectations() -> None:
    hits = [
        {
            "chunk_id": "chunk-1",
            "source_path": "source.md",
            "content": "Recall number D-0277-2024. Superpotent drug.",
            "document_type": "recall_notice",
            "section": "recall_notice",
            "recall_number": "D-0277-2024",
            "ndc": ["71449-072-41"],
            "lot": "2331062",
        }
    ]

    result = evaluate_hits(
        hits,
        {
            "any_hit": {
                "document_type": "recall_notice",
                "recall_number": "D-0277-2024",
                "content_contains": "superpotent",
            },
            "set": {
                "required_document_types": ["recall_notice"],
                "required_sections": ["recall_notice"],
                "min_evidence_count": 1,
                "must_have_citations": True,
                "ndc_match": ["71449-072-41"],
                "lot_match": ["2331062"],
            },
        },
    )

    assert result["passed"] is True
    assert result["rank"] == 1
    assert result["failures"] == []


def test_evaluate_hit_set_reports_missing_coverage() -> None:
    result = evaluate_hit_set(
        [{"chunk_id": "chunk-1", "source_path": "", "content": "body", "document_type": "label", "section": "warnings"}],
        {
            "required_document_types": ["recall_notice"],
            "required_sections": ["recall_notice"],
            "min_evidence_count": 2,
            "must_have_citations": True,
        },
    )

    assert result["passed"] is False
    assert "min_evidence_count 1 < 2" in result["failures"]
    assert "missing document_types: ['recall_notice']" in result["failures"]
    assert "missing sections: ['recall_notice']" in result["failures"]
    assert "one or more hits missing citation fields" in result["failures"]


def test_evaluate_empty_hits_can_mark_zero_evidence_as_expected() -> None:
    result = evaluate_empty_hits([], {"set": {"min_evidence_count": 0}})

    assert result == {
        "passed": True,
        "rank": None,
        "top_chunk_id": None,
        "top_score": None,
        "failures": [],
    }


def test_evaluate_sufficiency_passes_when_status_and_missing_types_match() -> None:
    result = evaluate_sufficiency(
        sufficiency_result(),
        {"evidence_status": "insufficient", "missing_document_types": ["sop"]},
    )

    assert result == {"passed": True, "failures": []}


def test_evaluate_sufficiency_fails_when_status_does_not_match() -> None:
    result = evaluate_sufficiency(sufficiency_result(), {"evidence_status": "sufficient"})

    assert result["passed"] is False
    assert "evidence_status 'insufficient' != 'sufficient'" in result["failures"]


def test_evaluate_sufficiency_fails_when_expected_missing_type_is_actually_found() -> None:
    result = evaluate_sufficiency(sufficiency_result(), {"missing_document_types": ["policy"]})

    assert result["passed"] is False
    assert "expected missing_document_types not actually missing: ['policy']" in result["failures"]


def test_evaluate_sufficiency_checks_coverage_score_bounds() -> None:
    below_min = evaluate_sufficiency(sufficiency_result(coverage_score=0.5), {"min_coverage_score": 0.8})
    above_max = evaluate_sufficiency(sufficiency_result(coverage_score=0.9), {"max_coverage_score": 0.8})

    assert below_min["passed"] is False
    assert above_max["passed"] is False


def test_evaluate_sufficiency_checks_weak_document_types_and_citations_ready() -> None:
    result = evaluate_sufficiency(
        sufficiency_result(weak_document_types=["policy"], citations_ready=False),
        {"weak_document_types": ["policy"], "citations_ready": False},
    )

    assert result == {"passed": True, "failures": []}


def test_evaluate_sufficiency_checks_failure_reasons() -> None:
    result = evaluate_sufficiency(
        sufficiency_result(failure_reasons=[{"reason": "missing_required_document_type"}]),
        {"failure_reasons": ["missing_required_document_type"]},
    )

    assert result == {"passed": True, "failures": []}


def test_summarize_results_reports_quality_metrics_and_failures() -> None:
    results = [
        {
            "expected": {
                "any_hit": {"document_type": "policy"},
                "set": {"required_document_types": ["policy"], "required_sections": ["required_actions"]},
                "sufficiency": {"evidence_status": "sufficient"},
            },
            "evaluation": {"passed": True, "rank": 2, "failures": []},
            "sufficiency": {
                "evidence_status": "sufficient",
                "citations_ready": True,
                "failure_reasons": [],
            },
            "hits": [{"document_type": "policy", "section": "required_actions"}],
        },
        {
            "expected": {
                "any_hit": {"document_type": "sop"},
                "set": {"required_document_types": ["sop"], "required_sections": ["procedure"]},
                "sufficiency": {"evidence_status": "sufficient"},
            },
            "evaluation": {"passed": False, "rank": None, "failures": ["no hit matched expected.any_hit"]},
            "sufficiency": {
                "evidence_status": "insufficient",
                "citations_ready": False,
                "failure_reasons": [{"reason": "citation_not_ready"}],
            },
            "hits": [{"document_type": "policy", "section": "required_actions"}],
        },
    ]

    summary = summarize_results(results)

    assert summary["passed"] == 1
    assert summary["pass_rate"] == 0.5
    assert summary["recall_at_k"] == 0.5
    assert summary["mrr"] == 0.25
    assert summary["document_type_coverage"] == 0.5
    assert summary["section_coverage"] == 0.5
    assert summary["citation_readiness_rate"] == 0.5
    assert summary["sufficiency_accuracy"] == 0.5
    assert summary["failure_distribution"]["sufficiency:citation_not_ready"] == 1


def test_build_retrieval_context_uses_explicit_context_including_ndc_and_lot() -> None:
    golden = golden_query(
        context={
            "event_type": "recall",
            "normalized_drug_name": "lidocaine",
            "recall_number": None,
            "ndc": ["52565-009-50"],
            "lot": "13262",
        }
    )

    context = build_retrieval_context(golden)

    assert context == RetrievalContext(
        event_type="recall",
        normalized_drug_name="lidocaine",
        recall_number=None,
        ndc=["52565-009-50"],
        lot="13262",
    )


def test_build_retrieval_context_falls_back_to_expected_any_hit_when_no_context_given() -> None:
    golden = golden_query(
        expected={"any_hit": {"event_type": "recall", "recall_number": "D-1"}},
    )

    context = build_retrieval_context(golden)

    assert context == context_from_expected(golden.expected)
    assert context.recall_number == "D-1"
