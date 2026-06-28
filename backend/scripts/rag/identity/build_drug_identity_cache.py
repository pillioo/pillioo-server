from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import httpx

from scripts.rag.identity.rxnorm_client import (
    DEFAULT_CACHE_PATH,
    load_identity_cache,
    normalize_identity_key,
    resolve_drug_identity,
    write_identity_cache,
)
from scripts.rag.openfda.common import DEFAULT_DRUG_LIST_PATH, load_drug_names
from scripts.rag.openfda.label_records import get_generic_name
from scripts.rag.openfda.recall_records import get_noisy_terms, infer_drug_name_from_recall


ROOT_DIR = Path(__file__).resolve().parents[3]
RAW_OPENFDA_DIR = ROOT_DIR / "data" / "rag" / "raw" / "openfda"


def load_raw_json_records(raw_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    if not raw_dir.exists():
        return records

    for path in sorted(raw_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            records.append(payload)

    return records


def collect_candidate_names(drug_list_path: Path) -> list[str]:
    names: list[str] = []

    for profile in ["label", "recall"]:
        names.extend(load_drug_names(drug_list_path, profile=profile))

    for record in load_raw_json_records(RAW_OPENFDA_DIR / "label"):
        names.append(get_generic_name(record, fallback_name=""))

    for record in load_raw_json_records(RAW_OPENFDA_DIR / "enforcement"):
        if get_noisy_terms(record):
            continue
        names.append(infer_drug_name_from_recall(record))

    seen: set[str] = set()
    unique_names: list[str] = []
    for name in names:
        key = normalize_identity_key(name)
        if key and key not in seen:
            unique_names.append(name)
            seen.add(key)

    return unique_names


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build RxNorm drug identity cache.")
    parser.add_argument("--drug-list", type=Path, default=DEFAULT_DRUG_LIST_PATH)
    parser.add_argument("--cache-path", type=Path, default=DEFAULT_CACHE_PATH)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--force", action="store_true", help="Refresh existing cache entries.")
    parser.add_argument("--reset", action="store_true", help="Clear the cache before rebuilding.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    cache = {} if args.reset else load_identity_cache(args.cache_path)
    names = collect_candidate_names(args.drug_list)

    if args.limit is not None:
        names = names[: args.limit]

    saved = 0
    skipped = 0
    failed = 0

    for name in names:
        key = normalize_identity_key(name)
        if not args.force and key in cache:
            skipped += 1
            continue

        try:
            cache[key] = resolve_drug_identity(name)
        except httpx.HTTPError as exc:
            failed += 1
            print(f"[WARN] Failed RxNorm lookup for {name!r}: {exc}")
            continue

        saved += 1
        identity = cache[key]
        print(
            "[OK] Cached drug identity: "
            f"{name} -> {identity.get('rxnorm_rxcui') or 'unmatched'} "
            f"({identity.get('match_basis')})"
        )

    path = write_identity_cache(cache, args.cache_path)

    print()
    print("[SUMMARY]")
    print(f"saved={saved}")
    print(f"skipped={skipped}")
    print(f"failed={failed}")
    print(f"cache_path={path}")


if __name__ == "__main__":
    main()
