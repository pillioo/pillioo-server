from __future__ import annotations

from scripts.rag.eval.run_retrieval_eval import dedupe_hits, evaluate_hits, matches_expected


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

    assert result == {
        "passed": True,
        "rank": 2,
        "top_chunk_id": "wrong",
        "top_score": 0.9,
    }


def test_evaluate_hits_reports_failure_without_match() -> None:
    result = evaluate_hits(
        [{"chunk_id": "wrong", "document_type": "label", "score": 0.7}],
        {"document_type": "recall_notice"},
    )

    assert result["passed"] is False
    assert result["rank"] is None
    assert result["top_chunk_id"] == "wrong"


def test_dedupe_hits_keeps_first_hit_for_repeated_field() -> None:
    hits = [
        {"chunk_id": "first", "content_hash": "same", "score": 0.9},
        {"chunk_id": "duplicate", "content_hash": "same", "score": 0.8},
        {"chunk_id": "second", "content_hash": "other", "score": 0.7},
        {"chunk_id": "missing_hash", "score": 0.6},
    ]

    deduped = dedupe_hits(hits, "content_hash")

    assert [hit["chunk_id"] for hit in deduped] == ["first", "second", "missing_hash"]
