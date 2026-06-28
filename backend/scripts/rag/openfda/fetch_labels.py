from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import httpx

from scripts.rag.openfda.common import (
    DEFAULT_DRUG_LIST_PATH,
    RAG_DIR,
    clean_markdown_dir,
    fetch_openfda_json,
    load_drug_names,
    save_raw_record,
    write_fetch_manifest,
)
from scripts.rag.openfda.label_records import (
    get_label_query_match_fields,
    label_record_to_markdown,
    make_document_id,
    rank_label_records,
    score_label_record,
)


BASE_URL = "https://api.fda.gov/drug/label.json"
RAW_DIR = RAG_DIR / "raw" / "openfda" / "label"
DOC_DIR = RAG_DIR / "documents" / "label"

DEFAULT_API_LIMIT_PER_DRUG = 10
DEFAULT_MAX_RECORDS_PER_DRUG = 2
DEFAULT_TARGET_LABEL_DOCUMENTS = 60
DEFAULT_MIN_RECORD_SCORE = 35


def build_label_query(drug_name: str) -> str:
    return (
        f'openfda.generic_name:"{drug_name}" '
        f'OR openfda.brand_name:"{drug_name}" '
        f'OR openfda.substance_name:"{drug_name}" '
        f'OR active_ingredient:"{drug_name}"'
    )


def fetch_label_payload(drug_name: str, limit: int) -> dict[str, Any]:
    return fetch_openfda_json(
        BASE_URL,
        params={
            "search": build_label_query(drug_name),
            "limit": limit,
        },
    )


def save_markdown(record: dict[str, Any], fallback_name: str) -> Path:
    DOC_DIR.mkdir(parents=True, exist_ok=True)

    document_id = make_document_id(record, fallback_name=fallback_name)
    path = DOC_DIR / f"{document_id}.md"
    path.write_text(
        label_record_to_markdown(record, fallback_name=fallback_name),
        encoding="utf-8",
    )

    return path


def select_best_query_drug(
    record: dict[str, Any],
    drug_names: list[str],
) -> tuple[str, int, list[str]] | None:
    best_match: tuple[str, int, list[str]] | None = None

    for drug_name in drug_names:
        match_fields = get_label_query_match_fields(record, drug_name)
        if not match_fields:
            continue

        score = score_label_record(record, query_drug_name=drug_name)
        if best_match is None or score > best_match[1]:
            best_match = (drug_name, score, match_fields)

    return best_match


def load_raw_records(raw_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    for raw_path in sorted(raw_dir.glob("*.json")):
        payload = json.loads(raw_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            records.append(payload)

    return records


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch openFDA label documents.")
    parser.add_argument("--target-documents", type=int, default=DEFAULT_TARGET_LABEL_DOCUMENTS)
    parser.add_argument("--limit", type=int, default=DEFAULT_API_LIMIT_PER_DRUG)
    parser.add_argument("--max-records-per-drug", type=int, default=DEFAULT_MAX_RECORDS_PER_DRUG)
    parser.add_argument("--min-score", type=int, default=DEFAULT_MIN_RECORD_SCORE)
    parser.add_argument("--drug-list", type=Path, default=DEFAULT_DRUG_LIST_PATH)
    parser.add_argument(
        "--from-raw",
        action="store_true",
        help="Regenerate markdown from existing raw openFDA JSON without network fetches.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete existing generated label markdown before fetching.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    drug_names = load_drug_names(args.drug_list, profile="label")

    total_saved = 0
    total_skipped = 0
    total_failed = 0
    seen_document_ids: set[str] = set()
    manifest_records: list[dict[str, Any]] = []

    if args.clean or args.from_raw:
        clean_markdown_dir(DOC_DIR)

    if args.from_raw:
        # Re-score saved API payloads when the filtering logic changes, without
        # consuming openFDA quota or depending on network access.
        raw_records = load_raw_records(RAW_DIR)
        ranked_raw_records: list[tuple[dict[str, Any], str, int, list[str]]] = []

        for record in raw_records:
            best_match = select_best_query_drug(record, drug_names)
            if best_match is None:
                total_skipped += 1
                continue

            drug_name, score, match_fields = best_match
            if score < args.min_score:
                total_skipped += 1
                continue

            ranked_raw_records.append((record, drug_name, score, match_fields))

        ranked_raw_records.sort(key=lambda item: item[2], reverse=True)

        for record, drug_name, score, match_fields in ranked_raw_records:
            if total_saved >= args.target_documents:
                break

            document_id = make_document_id(record, fallback_name=drug_name)
            if document_id in seen_document_ids:
                total_skipped += 1
                continue

            md_path = save_markdown(record, fallback_name=drug_name)
            seen_document_ids.add(document_id)
            total_saved += 1
            manifest_records.append(
                {
                    "drug": drug_name,
                    "query": "raw_rebuild",
                    "document_id": document_id,
                    "score": score,
                    "match_fields": match_fields,
                    "status": "saved",
                    "path": str(md_path),
                }
            )
            print(
                f"[OK] Rebuilt label document: {md_path.name} "
                f"(score={score}, drug={drug_name})"
            )

        write_fetch_manifest(
            "label",
            {
                "saved": total_saved,
                "skipped": total_skipped,
                "failed": total_failed,
                "raw_dir": str(RAW_DIR),
                "doc_dir": str(DOC_DIR),
                "drug_list": str(args.drug_list),
                "source_mode": "raw_rebuild",
                "records": manifest_records,
            },
        )

        print()
        print("[SUMMARY]")
        print(f"saved={total_saved}")
        print(f"skipped={total_skipped}")
        print(f"failed={total_failed}")
        print(f"raw_dir={RAW_DIR}")
        print(f"doc_dir={DOC_DIR}")
        return

    for drug_name in drug_names:
        if total_saved >= args.target_documents:
            break

        query = build_label_query(drug_name)

        try:
            payload = fetch_label_payload(drug_name, limit=args.limit)
        except httpx.HTTPStatusError as exc:
            print(f"[WARN] Failed to fetch label for {drug_name}: {exc}")
            total_failed += 1
            manifest_records.append({"drug": drug_name, "query": query, "status": "failed", "reason": str(exc)})
            continue
        except httpx.RequestError as exc:
            print(f"[WARN] Request error while fetching label for {drug_name}: {exc}")
            total_failed += 1
            manifest_records.append({"drug": drug_name, "query": query, "status": "failed", "reason": str(exc)})
            continue

        results = payload.get("results", [])
        if not isinstance(results, list) or not results:
            print(f"[WARN] No label found for {drug_name}")
            total_skipped += 1
            manifest_records.append({"drug": drug_name, "query": query, "status": "skipped", "reason": "no_results"})
            continue

        ranked_records = rank_label_records(results, query_drug_name=drug_name)
        saved_for_drug = 0

        for record in ranked_records:
            if saved_for_drug >= args.max_records_per_drug:
                break
            if total_saved >= args.target_documents:
                break

            score = score_label_record(record, query_drug_name=drug_name)
            document_id = make_document_id(record, fallback_name=drug_name)
            match_fields = get_label_query_match_fields(record, drug_name)
            base_manifest = {
                "drug": drug_name,
                "query": query,
                "document_id": document_id,
                "score": score,
                "match_fields": match_fields,
            }

            if not match_fields:
                total_skipped += 1
                manifest_records.append({**base_manifest, "status": "skipped", "reason": "query_mismatch"})
                continue

            if score < args.min_score:
                total_skipped += 1
                manifest_records.append({**base_manifest, "status": "skipped", "reason": f"low_score_{score}"})
                continue

            if document_id in seen_document_ids:
                total_skipped += 1
                manifest_records.append({**base_manifest, "status": "skipped", "reason": "duplicate"})
                continue

            save_raw_record(RAW_DIR, record, document_id=document_id)
            md_path = save_markdown(record, fallback_name=drug_name)

            seen_document_ids.add(document_id)
            saved_for_drug += 1
            total_saved += 1
            manifest_records.append({**base_manifest, "status": "saved", "path": str(md_path)})

            print(
                f"[OK] Saved label document: {md_path.name} "
                f"(score={score}, drug={drug_name})"
            )

        if saved_for_drug == 0:
            print(f"[WARN] No high-quality label selected for {drug_name}")

    write_fetch_manifest(
        "label",
        {
            "saved": total_saved,
            "skipped": total_skipped,
            "failed": total_failed,
            "raw_dir": str(RAW_DIR),
            "doc_dir": str(DOC_DIR),
            "drug_list": str(args.drug_list),
            "records": manifest_records,
        },
    )

    print()
    print("[SUMMARY]")
    print(f"saved={total_saved}")
    print(f"skipped={total_skipped}")
    print(f"failed={total_failed}")
    print(f"raw_dir={RAW_DIR}")
    print(f"doc_dir={DOC_DIR}")


if __name__ == "__main__":
    main()