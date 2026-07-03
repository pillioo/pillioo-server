from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from openai import OpenAI

from scripts.rag.embedding.config import (
    EMBEDDING_MODEL,
    MILVUS_COLLECTION,
    MILVUS_URI,
)

try:
    from pymilvus import MilvusClient
except ImportError as exc:  # pragma: no cover
    raise ImportError("pymilvus is required to run retrieval evaluation.") from exc


DEFAULT_GOLDEN_QUERIES_PATH = Path(__file__).with_name("golden_queries.yaml")

OUTPUT_FIELDS = [
    "chunk_id",
    "content",
    "document_id",
    "document_type",
    "event_type",
    "event_types_json",
    "section",
    "section_title",
    "title",
    "source_path",
    "drug_name",
    "normalized_drug_name",
    "rxnorm_rxcui",
    "classification",
    "ndc_json",
    "lot",
    "recall_number",
    "metadata_json",
    "embedding_model",
    "content_hash",
]


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


def embed_query(client: OpenAI, query: str, model: str) -> list[float]:
    response = client.embeddings.create(model=model, input=query)
    return response.data[0].embedding


def normalize_search_hit(hit: dict[str, Any]) -> dict[str, Any]:
    entity = hit.get("entity") or hit
    normalized = dict(entity)
    normalized["score"] = hit.get("distance", hit.get("score"))
    normalized["id"] = hit.get("id", entity.get("chunk_id"))
    return normalized


def search_milvus(
    client: MilvusClient,
    *,
    collection_name: str,
    query_embedding: list[float],
    top_k: int,
    filter_expr: str,
    nprobe: int,
    dedupe_field: str,
    oversample: int,
) -> list[dict[str, Any]]:
    search_limit = top_k if not dedupe_field else max(top_k, top_k * max(1, oversample))
    result = client.search(
        collection_name=collection_name,
        data=[query_embedding],
        filter=filter_expr,
        limit=search_limit,
        output_fields=OUTPUT_FIELDS,
        search_params={"metric_type": "COSINE", "params": {"nprobe": nprobe}},
        anns_field="embedding",
    )
    hits = [normalize_search_hit(hit) for hit in result[0]]
    if dedupe_field:
        hits = dedupe_hits(hits, dedupe_field)
    return hits[:top_k]


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


def evaluate_hits(hits: list[dict[str, Any]], expected: dict[str, Any]) -> dict[str, Any]:
    matching_index = next(
        (index for index, hit in enumerate(hits, start=1) if matches_expected(hit, expected)),
        None,
    )
    return {
        "passed": matching_index is not None,
        "rank": matching_index,
        "top_chunk_id": hits[0].get("chunk_id") if hits else None,
        "top_score": hits[0].get("score") if hits else None,
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
        "recall_number": hit.get("recall_number"),
        "content_preview": content[:240].replace("\n", " "),
    }


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
    openai_client = OpenAI()
    milvus_client = MilvusClient(uri=uri)

    results: list[dict[str, Any]] = []
    for golden in queries:
        query_embedding = embed_query(openai_client, golden.query, model)
        hits = search_milvus(
            milvus_client,
            collection_name=collection_name,
            query_embedding=query_embedding,
            top_k=golden.top_k,
            filter_expr=golden.filter,
            nprobe=nprobe,
            dedupe_field=dedupe_field,
            oversample=oversample,
        )
        evaluation = evaluate_hits(hits, golden.expected)
        results.append(
            {
                "id": golden.id,
                "query": golden.query,
                "filter": golden.filter,
                "expected": golden.expected,
                "evaluation": evaluation,
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
