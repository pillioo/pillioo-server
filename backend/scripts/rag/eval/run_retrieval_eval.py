from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.rag.models import RetrievalContext
from app.rag.service import RetrievalService
from scripts.rag.embedding.config import (
    EMBEDDING_MODEL,
    MILVUS_COLLECTION,
    MILVUS_URI,
)


DEFAULT_GOLDEN_QUERIES_PATH = Path(__file__).with_name("golden_queries.yaml")

@dataclass(frozen=True)
class GoldenQuery:
    id: str
    query: str
    top_k: int
    filter: str
    expected: dict[str, Any]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run RAG retrieval smoke/eval queries against Milvus.")
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN_QUERIES_PATH)
    parser.add_argument("--query", default=None, help="Run a single ad hoc query instead of the golden query file.")
    parser.add_argument("--filter", default="", help="Milvus scalar filter for --query mode.")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--uri", default=MILVUS_URI)
    parser.add_argument("--collection", default=MILVUS_COLLECTION)
    parser.add_argument("--model", default=EMBEDDING_MODEL)
    parser.add_argument("--nprobe", type=int, default=16)
    parser.add_argument(
        "--dedupe-field",
        default="content_hash",
        help="Remove repeated hits with the same field value. Use an empty value to disable.",
    )
    parser.add_argument(
        "--oversample",
        type=int,
        default=4,
        help="Search top_k * oversample candidates before deduping.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output.")
    return parser


def load_golden_queries(path: Path) -> list[GoldenQuery]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if not isinstance(payload, list):
        raise ValueError(f"Golden query file must contain a list: {path}")

    queries: list[GoldenQuery] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError(f"Golden query entries must be objects: {item!r}")
        expected = item.get("expected") or {}
        if not isinstance(expected, dict):
            raise ValueError(f"Golden query expected value must be an object: {item!r}")
        queries.append(
            GoldenQuery(
                id=str(item["id"]),
                query=str(item["query"]),
                top_k=int(item.get("top_k") or 5),
                filter=str(item.get("filter") or ""),
                expected=expected,
            )
        )
    return queries


def dedupe_hits(hits: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for hit in hits:
        value = hit.get(field)
        if value in (None, ""):
            deduped.append(hit)
            continue
        key = str(value)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(hit)
    return deduped


def matches_expected(hit: dict[str, Any], expected: dict[str, Any]) -> bool:
    for field, expected_value in expected.items():
        if field == "content_contains":
            content = str(hit.get("content") or "").lower()
            expected_terms = expected_value if isinstance(expected_value, list) else [expected_value]
            if not all(str(term).lower() in content for term in expected_terms):
                return False
            continue

        if field == "any_section":
            expected_sections = {str(section) for section in expected_value}
            if str(hit.get("section")) not in expected_sections:
                return False
            continue

        if hit.get(field) != expected_value:
            return False

    return True


def split_expected(expected: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if "any_hit" in expected or "set" in expected:
        any_hit = expected.get("any_hit") or {}
        set_expected = expected.get("set") or {}
        if not isinstance(any_hit, dict) or not isinstance(set_expected, dict):
            raise ValueError("expected.any_hit and expected.set must be objects when provided.")
        return any_hit, set_expected
    return expected, {}


def list_values(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def has_citation_fields(hit: dict[str, Any]) -> bool:
    return all(str(hit.get(field) or "").strip() for field in ["chunk_id", "source_path", "content"])


def evaluate_hit_set(hits: list[dict[str, Any]], expected: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []

    min_evidence_count = expected.get("min_evidence_count")
    if min_evidence_count is not None and len(hits) < int(min_evidence_count):
        failures.append(f"min_evidence_count {len(hits)} < {min_evidence_count}")

    required_document_types = {str(value) for value in list_values(expected.get("required_document_types"))}
    if required_document_types:
        actual_document_types = {str(hit.get("document_type")) for hit in hits}
        missing = sorted(required_document_types - actual_document_types)
        if missing:
            failures.append(f"missing document_types: {missing}")

    required_sections = {str(value) for value in list_values(expected.get("required_sections"))}
    if required_sections:
        actual_sections = {str(hit.get("section")) for hit in hits}
        missing = sorted(required_sections - actual_sections)
        if missing:
            failures.append(f"missing sections: {missing}")

    if expected.get("must_have_citations") and not all(has_citation_fields(hit) for hit in hits):
        failures.append("one or more hits missing citation fields")

    ndc_matches = {str(value) for value in list_values(expected.get("ndc_match"))}
    if ndc_matches:
        actual_ndcs = {str(ndc) for hit in hits for ndc in list_values(hit.get("ndc"))}
        missing = sorted(ndc_matches - actual_ndcs)
        if missing:
            failures.append(f"missing ndc matches: {missing}")

    lot_matches = {str(value) for value in list_values(expected.get("lot_match"))}
    if lot_matches:
        actual_lots = {str(hit.get("lot")) for hit in hits if hit.get("lot")}
        missing = sorted(lot_matches - actual_lots)
        if missing:
            failures.append(f"missing lot matches: {missing}")

    return {
        "passed": not failures,
        "failures": failures,
    }


def evaluate_hits(hits: list[dict[str, Any]], expected: dict[str, Any]) -> dict[str, Any]:
    any_hit_expected, set_expected = split_expected(expected)
    matching_index = next(
        (index for index, hit in enumerate(hits, start=1) if matches_expected(hit, any_hit_expected)),
        None,
    ) if any_hit_expected else None
    any_hit_passed = matching_index is not None if any_hit_expected else True
    set_evaluation = evaluate_hit_set(hits, set_expected) if set_expected else {"passed": True, "failures": []}
    passed = any_hit_passed and bool(set_evaluation["passed"])
    failures = []
    if not any_hit_passed:
        failures.append("no hit matched expected.any_hit")
    failures.extend(set_evaluation["failures"])
    return {
        "passed": passed,
        "rank": matching_index,
        "top_chunk_id": hits[0].get("chunk_id") if hits else None,
        "top_score": hits[0].get("score") if hits else None,
        "failures": failures,
    }


def is_correctly_empty_expected(expected: dict[str, Any]) -> bool:
    _, set_expected = split_expected(expected)
    min_evidence_count = set_expected.get("min_evidence_count")
    return min_evidence_count is not None and int(min_evidence_count) == 0


def evaluate_empty_hits(hits: list[dict[str, Any]], expected: dict[str, Any]) -> dict[str, Any]:
    if hits or not is_correctly_empty_expected(expected):
        return evaluate_hits(hits, expected)
    return {
        "passed": True,
        "rank": None,
        "top_chunk_id": None,
        "top_score": None,
        "failures": [],
    }


def compact_hit(hit: dict[str, Any]) -> dict[str, Any]:
    content = str(hit.get("content") or "")
    return {
        "score": hit.get("score"),
        "chunk_id": hit.get("chunk_id"),
        "document_type": hit.get("document_type"),
        "event_type": hit.get("event_type"),
        "section": hit.get("section"),
        "title": hit.get("title"),
        "drug_name": hit.get("drug_name"),
        "normalized_drug_name": hit.get("normalized_drug_name"),
        "rxnorm_rxcui": hit.get("rxnorm_rxcui"),
        "classification": hit.get("classification"),
        "ndc": hit.get("ndc"),
        "recall_number": hit.get("recall_number"),
        "content_preview": content[:240].replace("\n", " "),
    }


def context_from_expected(expected: dict[str, Any]) -> RetrievalContext:
    any_hit, _ = split_expected(expected)
    return RetrievalContext(
        event_type=any_hit.get("event_type"),
        normalized_drug_name=any_hit.get("normalized_drug_name"),
        rxnorm_rxcui=any_hit.get("rxnorm_rxcui"),
        recall_number=any_hit.get("recall_number"),
        classification=any_hit.get("classification"),
    )


def run_queries(
    queries: list[GoldenQuery],
    *,
    uri: str,
    collection_name: str,
    model: str,
    nprobe: int,
    dedupe_field: str,
    oversample: int,
) -> list[dict[str, Any]]:
    retrieval_service = RetrievalService.from_milvus(
        uri=uri,
        collection_name=collection_name,
        embedding_model=model,
        nprobe=nprobe,
        oversample=oversample,
    )

    results: list[dict[str, Any]] = []
    for golden in queries:
        evidence_result = retrieval_service.retrieve(
            query=golden.query,
            context=context_from_expected(golden.expected),
            top_k=golden.top_k,
            filter_override=golden.filter or None,
        )
        hits = [chunk.to_dict() for chunk in evidence_result.chunks]
        if dedupe_field:
            hits = dedupe_hits(hits, dedupe_field)[: golden.top_k]
        evaluation = evaluate_empty_hits(hits, golden.expected)
        results.append(
            {
                "id": golden.id,
                "query": golden.query,
                "filter": golden.filter,
                "expected": golden.expected,
                "evaluation": evaluation,
                "sufficiency": {
                    "evidence_status": evidence_result.sufficiency.evidence_status,
                    "coverage_score": evidence_result.sufficiency.coverage_score,
                    "missing_document_types": evidence_result.sufficiency.missing_document_types,
                    "weak_document_types": evidence_result.sufficiency.weak_document_types,
                    "citations_ready": evidence_result.sufficiency.citations_ready,
                },
                "hits": [compact_hit(hit) for hit in hits],
            }
        )
    return results


def print_text_report(results: list[dict[str, Any]]) -> None:
    passed = sum(1 for result in results if result["evaluation"]["passed"])
    print(f"[SUMMARY] passed={passed}/{len(results)}")
    for result in results:
        status = "PASS" if result["evaluation"]["passed"] else "FAIL"
        rank = result["evaluation"]["rank"]
        print(f"\n[{status}] {result['id']} rank={rank}")
        print(f"query={result['query']}")
        if result["filter"]:
            print(f"filter={result['filter']}")
        for index, hit in enumerate(result["hits"], start=1):
            print(
                f"  {index}. score={hit['score']} type={hit['document_type']} "
                f"section={hit['section']} chunk={hit['chunk_id']}"
            )
            print(f"     {hit['content_preview']}")


def main() -> None:
    args = build_parser().parse_args()
    if args.query:
        queries = [
            GoldenQuery(
                id="ad_hoc",
                query=args.query,
                top_k=args.top_k,
                filter=args.filter,
                expected={},
            )
        ]
    else:
        queries = load_golden_queries(args.golden)

    results = run_queries(
        queries,
        uri=args.uri,
        collection_name=args.collection,
        model=args.model,
        nprobe=args.nprobe,
        dedupe_field=args.dedupe_field,
        oversample=args.oversample,
    )

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print_text_report(results)

    failed = [result for result in results if result["expected"] and not result["evaluation"]["passed"]]
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
