from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import httpx

from scripts.rag.openfda.common import (
    DEFAULT_DRUG_LIST_PATH,
    MANIFEST_PATH,
    RAG_DIR,
    clean_markdown_dir,
    fetch_openfda_json,
    load_drug_names,
    save_raw_record,
    write_fetch_manifest,
)
from scripts.rag.openfda.recall_records import (
    get_matching_drug_names,
    get_noisy_terms,
    infer_drug_name_from_recall,
    make_document_id,
    make_recall_key,
    rank_recall_records,
    recall_record_to_markdown,
    score_recall_record,
)


BASE_URL = "https://api.fda.gov/drug/enforcement.json"
RAW_DIR = RAG_DIR / "raw" / "openfda" / "enforcement"
DOC_DIR = RAG_DIR / "documents" / "recall_notice"

DEFAULT_API_LIMIT_PER_DRUG = 10
DEFAULT_MAX_RECORDS_PER_DRUG = 3
DEFAULT_TARGET_RECALL_DOCUMENTS = 50
DEFAULT_MIN_RECORD_SCORE = 20
DEFAULT_BROAD_FETCH_LIMIT = 100
DEFAULT_BROAD_FETCH_PAGES = 2

BROAD_RECALL_QUERIES = [
    'product_type:"Drugs" AND classification:"Class I"',
    'product_type:"Drugs" AND classification:"Class II"',
    'product_type:"Drugs" AND reason_for_recall:"labeling"',
    'product_type:"Drugs" AND reason_for_recall:"particulate"',
    'product_type:"Drugs" AND reason_for_recall:"sterility"',
    'product_type:"Drugs" AND reason_for_recall:"contamination"',
]


def build_targeted_query(drug_name: str) -> str:
    return (
        f'product_description:"{drug_name}" '
        f'OR reason_for_recall:"{drug_name}" '
        f'OR code_info:"{drug_name}"'
    )


def fetch_recalls_by_drug(drug_name: str, limit: int) -> dict[str, Any]:
    return fetch_openfda_json(
        BASE_URL,
        params={
            "search": build_targeted_query(drug_name),
            "limit": limit,
        },
    )


def fetch_recalls_by_query(query: str, limit: int, skip: int = 0) -> dict[str, Any]:
    return fetch_openfda_json(
        BASE_URL,
        params={
            "search": query,
            "limit": limit,
            "skip": skip,
        },
    )


def save_markdown(record: dict[str, Any], drug_name: str, source_mode: str) -> Path:
    DOC_DIR.mkdir(parents=True, exist_ok=True)

    document_id = make_document_id(record, fallback_drug_name=drug_name)
    path = DOC_DIR / f"{document_id}.md"
    path.write_text(
        recall_record_to_markdown(
            record,
            fallback_drug_name=drug_name,
            source_mode=source_mode,
        ),
        encoding="utf-8",
    )

    return path


def save_record_if_valid(
    record: dict[str, Any],
    drug_name: str,
    seen_recall_keys: set[str],
    source_mode: str,
    manifest_records: list[dict[str, Any]],
    query: str,
    min_score: int,
    query_drug_name: str | None = None,
    broad_drug_names: list[str] | None = None,
) -> tuple[bool, str]:
    recall_key = make_recall_key(record)
    if not recall_key:
        manifest_records.append({"drug": drug_name, "query": query, "source_mode": source_mode, "status": "skipped", "reason": "missing_recall_key"})
        return False, "missing_recall_key"
    document_id = make_document_id(record, fallback_drug_name=drug_name)
    score = score_recall_record(record, query_drug_name=query_drug_name)
    noisy_terms = get_noisy_terms(record)
    broad_matches = (
        get_matching_drug_names(
            record,
            broad_drug_names,
            product_only=True,
            primary_only=True,
        )
        if source_mode == "broad" and broad_drug_names
        else []
    )
    manifest = {
        "drug": drug_name,
        "query": query,
        "source_mode": source_mode,
        "recall_key": recall_key,
        "document_id": document_id,
        "score": score,
        "noisy_terms": noisy_terms,
        "broad_matches": broad_matches,
    }
    if recall_key in seen_recall_keys:
        manifest_records.append({**manifest, "status": "skipped", "reason": "duplicate"})
        return False, "duplicate"
    if source_mode == "broad" and noisy_terms:
        reason = "broad_noisy_terms_" + ",".join(noisy_terms)
        manifest_records.append({**manifest, "status": "skipped", "reason": reason})
        return False, reason
    if source_mode == "broad" and broad_drug_names and not broad_matches:
        reason = "broad_no_drug_list_match"
        manifest_records.append({**manifest, "status": "skipped", "reason": reason})
        return False, reason
    if source_mode == "targeted" and query_drug_name:
        targeted_matches = get_matching_drug_names(
            record,
            [query_drug_name],
            product_only=True,
        )
        if not targeted_matches:
            reason = "targeted_product_mismatch"
            manifest_records.append({**manifest, "status": "skipped", "reason": reason})
            return False, reason
    if score < min_score:
        manifest_records.append({**manifest, "status": "skipped", "reason": f"low_score_{score}"})
        return False, f"low_score_{score}"
    save_raw_record(RAW_DIR, record, document_id=document_id)
    md_path = save_markdown(record, drug_name=drug_name, source_mode=source_mode)
    seen_recall_keys.add(recall_key)
    manifest_records.append({**manifest, "status": "saved", "path": str(md_path)})
    print(
        f"[OK] Saved recall document: {md_path.name} "
        f"(score={score}, drug={drug_name}, mode={source_mode})"
    )
    return True, "saved"


def targeted_fetch(
    drug_names: list[str],
    seen_recall_keys: set[str],
    total_saved: int,
    args: argparse.Namespace,
    manifest_records: list[dict[str, Any]],
) -> tuple[int, int, int]:
    saved = 0
    skipped = 0
    failed = 0

    for drug_name in drug_names:
        if total_saved + saved >= args.target_documents:
            break

        query = build_targeted_query(drug_name)

        try:
            payload = fetch_recalls_by_drug(drug_name, limit=args.limit)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                print(f"[WARN] No recall records found for {drug_name}")
                skipped += 1
                manifest_records.append({"drug": drug_name, "query": query, "source_mode": "targeted", "status": "skipped", "reason": "no_results"})
                continue

            print(f"[WARN] Failed to fetch recall records for {drug_name}: {exc}")
            failed += 1
            manifest_records.append({"drug": drug_name, "query": query, "source_mode": "targeted", "status": "failed", "reason": str(exc)})
            continue
        except httpx.RequestError as exc:
            print(f"[WARN] Request error while fetching recall records for {drug_name}: {exc}")
            failed += 1
            manifest_records.append({"drug": drug_name, "query": query, "source_mode": "targeted", "status": "failed", "reason": str(exc)})
            continue

        results = payload.get("results", [])
        if not isinstance(results, list) or not results:
            print(f"[WARN] No recall records found for {drug_name}")
            skipped += 1
            manifest_records.append({"drug": drug_name, "query": query, "source_mode": "targeted", "status": "skipped", "reason": "no_results"})
            continue

        ranked_records = rank_recall_records(results, query_drug_name=drug_name)
        saved_for_drug = 0

        for record in ranked_records:
            if saved_for_drug >= args.max_records_per_drug:
                break
            if total_saved + saved >= args.target_documents:
                break

            ok, reason = save_record_if_valid(
                record=record,
                drug_name=drug_name,
                seen_recall_keys=seen_recall_keys,
                source_mode="targeted",
                manifest_records=manifest_records,
                query=query,
                min_score=args.min_score,
                query_drug_name=drug_name,
            )

            if ok:
                saved += 1
                saved_for_drug += 1
            else:
                skipped += 1
                if reason != "duplicate":
                    print(f"[SKIP] {reason} for drug={drug_name}")

        if saved_for_drug == 0:
            print(f"[WARN] No high-quality recall selected for {drug_name}")

    return saved, skipped, failed


def broad_backfill(
    drug_names: list[str],
    seen_recall_keys: set[str],
    total_saved: int,
    args: argparse.Namespace,
    manifest_records: list[dict[str, Any]],
) -> tuple[int, int, int]:
    saved = 0
    skipped = 0
    failed = 0

    if args.no_broad or total_saved >= args.target_documents:
        return saved, skipped, failed

    print()
    print("[INFO] Starting broad recall backfill...")

    for query in BROAD_RECALL_QUERIES:
        if total_saved + saved >= args.target_documents:
            break

        for page in range(args.broad_pages):
            if total_saved + saved >= args.target_documents:
                break

            skip = page * args.broad_limit

            try:
                payload = fetch_recalls_by_query(query=query, limit=args.broad_limit, skip=skip)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    print(f"[WARN] No broad recall records found for query={query}")
                    skipped += 1
                    break

                print(f"[WARN] Failed broad query={query}: {exc}")
                failed += 1
                break
            except httpx.RequestError as exc:
                print(f"[WARN] Request error for broad query={query}: {exc}")
                failed += 1
                break

            results = payload.get("results", [])
            if not isinstance(results, list) or not results:
                print(f"[WARN] Empty broad result for query={query}")
                skipped += 1
                break

            ranked_records = rank_recall_records(results, query_drug_name=None)

            for record in ranked_records:
                if total_saved + saved >= args.target_documents:
                    break

                matching_drug_names = get_matching_drug_names(
                    record,
                    drug_names,
                    product_only=True,
                    primary_only=True,
                )
                inferred_drug_name = (
                    matching_drug_names[0]
                    if matching_drug_names
                    else infer_drug_name_from_recall(record)
                )
                ok, _reason = save_record_if_valid(
                    record=record,
                    drug_name=inferred_drug_name,
                    seen_recall_keys=seen_recall_keys,
                    source_mode="broad",
                    manifest_records=manifest_records,
                    query=query,
                    min_score=args.min_score,
                    query_drug_name=None,
                    broad_drug_names=drug_names,
                )

                if ok:
                    saved += 1
                else:
                    skipped += 1

    return saved, skipped, failed


def load_raw_records_from_manifest() -> list[tuple[dict[str, Any], dict[str, Any]]]:
    if not MANIFEST_PATH.exists():
        return []

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    recall_manifest = manifest.get("recall", {})
    records = recall_manifest.get("records", [])
    if not isinstance(records, list):
        return []

    raw_records: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for item in records:
        if not isinstance(item, dict) or item.get("status") != "saved":
            continue

        document_id = str(item.get("document_id") or "")
        if not document_id:
            continue

        raw_path = RAW_DIR / f"{document_id}.json"
        if not raw_path.exists():
            continue

        payload = json.loads(raw_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            raw_records.append((payload, item))

    return raw_records


def rebuild_from_raw(
    drug_names: list[str],
    seen_recall_keys: set[str],
    args: argparse.Namespace,
    manifest_records: list[dict[str, Any]],
) -> tuple[int, int, int]:
    saved = 0
    skipped = 0
    failed = 0

    for record, item in load_raw_records_from_manifest():
        if saved >= args.target_documents:
            break

        source_mode = str(item.get("source_mode") or "targeted")
        if source_mode == "broad":
            # Raw rebuild applies the same stricter broad matching as live
            # fetches, so old noisy records do not re-enter generated docs.
            matching_drug_names = get_matching_drug_names(
                record,
                drug_names,
                product_only=True,
                primary_only=True,
            )
            if not matching_drug_names:
                skipped += 1
                continue
            drug_name = matching_drug_names[0]
        else:
            matching_drug_names = get_matching_drug_names(record, drug_names)
            drug_name = str(item.get("drug") or (matching_drug_names[0] if matching_drug_names else infer_drug_name_from_recall(record)))

        ok, _reason = save_record_if_valid(
            record=record,
            drug_name=drug_name,
            seen_recall_keys=seen_recall_keys,
            source_mode=source_mode,
            manifest_records=manifest_records,
            query="raw_rebuild",
            min_score=args.min_score,
            query_drug_name=drug_name if source_mode == "targeted" else None,
            broad_drug_names=drug_names if source_mode == "broad" else None,
        )

        if ok:
            saved += 1
        else:
            skipped += 1

    return saved, skipped, failed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch openFDA recall notice documents.")
    parser.add_argument("--target-documents", type=int, default=DEFAULT_TARGET_RECALL_DOCUMENTS)
    parser.add_argument("--limit", type=int, default=DEFAULT_API_LIMIT_PER_DRUG)
    parser.add_argument("--max-records-per-drug", type=int, default=DEFAULT_MAX_RECORDS_PER_DRUG)
    parser.add_argument("--min-score", type=int, default=DEFAULT_MIN_RECORD_SCORE)
    parser.add_argument("--drug-list", type=Path, default=DEFAULT_DRUG_LIST_PATH)
    parser.add_argument(
        "--from-raw",
        action="store_true",
        help="Regenerate markdown from existing raw enforcement JSON without network fetches.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete existing generated recall markdown before fetching.",
    )
    parser.add_argument("--no-broad", action="store_true", help="Disable broad recall backfill.")
    parser.add_argument("--broad-limit", type=int, default=DEFAULT_BROAD_FETCH_LIMIT)
    parser.add_argument("--broad-pages", type=int, default=DEFAULT_BROAD_FETCH_PAGES)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    drug_names = load_drug_names(args.drug_list, profile="recall")

    if  args.clean or args.from_raw:
        clean_markdown_dir(DOC_DIR)

    seen_recall_keys: set[str] = set()
    manifest_records: list[dict[str, Any]] = []

    if args.from_raw:
        rebuilt_saved, rebuilt_skipped, rebuilt_failed = rebuild_from_raw(
            drug_names=drug_names,
            seen_recall_keys=seen_recall_keys,
            args=args,
            manifest_records=manifest_records,
        )
        broad_saved = sum(
            1
            for item in manifest_records
            if item.get("status") == "saved" and item.get("source_mode") == "broad"
        )
        targeted_saved = rebuilt_saved - broad_saved
        targeted_skipped = rebuilt_skipped
        targeted_failed = rebuilt_failed
        broad_skipped = 0
        broad_failed = 0
    else:
        targeted_saved, targeted_skipped, targeted_failed = targeted_fetch(
            drug_names=drug_names,
            seen_recall_keys=seen_recall_keys,
            total_saved=0,
            args=args,
            manifest_records=manifest_records,
        )

        broad_saved, broad_skipped, broad_failed = broad_backfill(
            drug_names=drug_names,
            seen_recall_keys=seen_recall_keys,
            total_saved=targeted_saved,
            args=args,
            manifest_records=manifest_records,
        )

    total_saved = targeted_saved + broad_saved
    total_skipped = targeted_skipped + broad_skipped
    total_failed = targeted_failed + broad_failed

    write_fetch_manifest(
        "recall",
        {
            "target_saved": targeted_saved,
            "broad_saved": broad_saved,
            "saved": total_saved,
            "skipped": total_skipped,
            "failed": total_failed,
            "raw_dir": str(RAW_DIR),
            "doc_dir": str(DOC_DIR),
            "drug_list": str(args.drug_list),
            "source_mode": "raw_rebuild" if args.from_raw else "fetch",
            "records": manifest_records,
        },
    )

    print()
    print("[SUMMARY]")
    print(f"target_saved={targeted_saved}")
    print(f"broad_saved={broad_saved}")
    print(f"saved={total_saved}")
    print(f"skipped={total_skipped}")
    print(f"failed={total_failed}")
    print(f"raw_dir={RAW_DIR}")
    print(f"doc_dir={DOC_DIR}")


if __name__ == "__main__":
    main()