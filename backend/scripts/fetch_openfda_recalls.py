from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv


BASE_URL = "https://api.fda.gov/drug/enforcement.json"

ROOT_DIR = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT_DIR / "data" / "rag" / "raw" / "openfda" / "enforcement"
DOC_DIR = ROOT_DIR / "data" / "rag" / "documents" / "recall_notice"

API_LIMIT_PER_DRUG = 10
MAX_RECORDS_PER_DRUG = 3
TARGET_RECALL_DOCUMENTS = 50
MIN_RECORD_SCORE = 6

BROAD_FETCH_LIMIT = 100
BROAD_FETCH_PAGES = 2


DRUG_NAMES = [
    # Sedation / anesthesia / analgesics
    "midazolam",
    "propofol",
    "fentanyl",
    "morphine sulfate",
    "hydromorphone",
    "ketamine",
    "dexmedetomidine",
    "bupivacaine",
    "lidocaine",

    # Vasopressors / emergency medications
    "epinephrine",
    "norepinephrine",
    "phenylephrine",
    "dopamine",
    "dobutamine",
    "naloxone",

    # Antibiotics
    "vancomycin",
    "ceftriaxone",
    "cefazolin",
    "piperacillin",
    "tazobactam",
    "meropenem",
    "azithromycin",
    "ciprofloxacin",
    "metronidazole",

    # Anticoagulants / cardiovascular
    "heparin",
    "heparin sodium",
    "enoxaparin",
    "warfarin",
    "alteplase",
    "amiodarone",
    "nitroglycerin",

    # Endocrine / metabolic
    "insulin",
    "insulin regular human",
    "insulin glargine",
    "potassium chloride",
    "magnesium sulfate",
    "dextrose",
    "sodium chloride",

    # Antiemetic / GI / pain
    "ondansetron",
    "metoclopramide",
    "pantoprazole",
    "ketorolac",
    "acetaminophen",

    # Steroids / oncology-related
    "dexamethasone",
    "methylprednisolone",
    "methotrexate",
    "cisplatin",
]


BROAD_RECALL_QUERIES = [
    'product_type:"Drugs" AND classification:"Class I"',
    'product_type:"Drugs" AND classification:"Class II"',
    'product_type:"Drugs" AND reason_for_recall:"labeling"',
    'product_type:"Drugs" AND reason_for_recall:"particulate"',
    'product_type:"Drugs" AND reason_for_recall:"sterility"',
    'product_type:"Drugs" AND reason_for_recall:"contamination"',
]


def slugify(value: str, max_length: int = 80) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = value.strip("_") or "unknown"
    return value[:max_length].strip("_") or "unknown"


def clean_text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def yaml_quote(value: str) -> str:
    return json.dumps(value or "", ensure_ascii=False)


def normalize_drug_name(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"\s+", " ", value)
    return value or "unknown"


def get_text(record: dict[str, Any], field: str) -> str:
    value = record.get(field, "")
    if value is None:
        return ""
    return clean_text(str(value))


def extract_ndc(text: str) -> str:
    match = re.search(r"\b\d{4,5}-\d{3,4}-\d{1,2}\b", text)
    return match.group(0) if match else ""


def extract_lot(text: str) -> str:
    patterns = [
        r"(?:lot|lot number|lot no\.?)[:\s#-]*([A-Z0-9-]+)",
        r"(?:lots?)[:\s#-]*([A-Z0-9-]+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1)

    return ""


def normalize_date_yyyymmdd(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r"\d{8}", value):
        return f"{value[:4]}-{value[4:6]}-{value[6:8]}"
    return ""


def infer_reason_category(reason: str) -> str:
    reason_lower = reason.lower()

    rules = [
        ("labeling_issue", ["label", "labeling", "mislabel", "incorrect instructions"]),
        ("sterility_issue", ["sterility", "sterile", "lack of sterility"]),
        ("contamination", ["contamination", "contaminated", "microbial", "bacterial"]),
        ("particulate_matter", ["particulate", "particles", "foreign matter"]),
        ("defective_delivery_system", ["delivery system", "clogging", "device", "syringe"]),
        ("subpotent", ["subpotent", "low potency", "lack of potency"]),
        ("superpotent", ["superpotent", "high potency", "higher potency"]),
        ("packaging_defect", ["packaging", "container", "carton", "blister"]),
        ("cgmp_deviation", ["cgmp", "current good manufacturing practice"]),
    ]

    for category, keywords in rules:
        if any(keyword in reason_lower for keyword in keywords):
            return category

    return "other"


def make_recall_key(record: dict[str, Any]) -> str:
    recall_number = get_text(record, "recall_number")
    event_id = get_text(record, "event_id")
    return recall_number or event_id


def make_document_id(record: dict[str, Any], fallback_drug_name: str) -> str:
    recall_key = make_recall_key(record)
    identifier = recall_key or fallback_drug_name
    return f"recall-{slugify(identifier, max_length=50)}"


def infer_drug_name_from_recall(record: dict[str, Any]) -> str:
    product_description = get_text(record, "product_description")

    if not product_description:
        return "unknown"

    # Usually the first comma-separated segment contains the product/drug name.
    head = product_description.split(",")[0]

    # Remove common dosage/form/noise words.
    head = re.sub(
        r"\b("
        r"injection|injectable|usp|solution|tablets?|capsules?|"
        r"rx only|sterile|single-dose|prefilled|syringes?|vials?|"
        r"kit|kits|carton|bottle|bags?|iv|use"
        r")\b",
        "",
        head,
        flags=re.IGNORECASE,
    )

    head = re.sub(r"\([^)]*\)", "", head)
    head = re.sub(r"\d+(\.\d+)?\s*(mg|mcg|ml|l|%)", "", head, flags=re.IGNORECASE)
    head = re.sub(r"[^A-Za-z0-9 /+-]+", " ", head)
    head = re.sub(r"\s+", " ", head).strip()

    if not head:
        return "unknown"

    return normalize_drug_name(head[:80])


def fetch_recalls_by_drug(
    drug_name: str,
    limit: int = API_LIMIT_PER_DRUG,
) -> dict[str, Any]:
    load_dotenv()

    params: dict[str, Any] = {
        "search": (
            f'product_description:"{drug_name}" '
            f'OR reason_for_recall:"{drug_name}" '
            f'OR code_info:"{drug_name}"'
        ),
        "limit": limit,
    }

    api_key = os.getenv("OPENFDA_API_KEY")
    if api_key:
        params["api_key"] = api_key

    with httpx.Client(timeout=30.0) as client:
        response = client.get(BASE_URL, params=params)
        response.raise_for_status()
        return response.json()


def fetch_recalls_by_query(
    query: str,
    limit: int = BROAD_FETCH_LIMIT,
    skip: int = 0,
) -> dict[str, Any]:
    load_dotenv()

    params: dict[str, Any] = {
        "search": query,
        "limit": limit,
        "skip": skip,
    }

    api_key = os.getenv("OPENFDA_API_KEY")
    if api_key:
        params["api_key"] = api_key

    with httpx.Client(timeout=30.0) as client:
        response = client.get(BASE_URL, params=params)
        response.raise_for_status()
        return response.json()


def score_recall_record(record: dict[str, Any], query_drug_name: str | None = None) -> int:
    score = 0

    classification = get_text(record, "classification")
    status = get_text(record, "status")
    product_type = get_text(record, "product_type")
    product_description = get_text(record, "product_description")
    reason_for_recall = get_text(record, "reason_for_recall")
    product_quantity = get_text(record, "product_quantity")
    code_info = get_text(record, "code_info")
    distribution_pattern = get_text(record, "distribution_pattern")
    recall_number = get_text(record, "recall_number")
    event_id = get_text(record, "event_id")
    recall_initiation_date = get_text(record, "recall_initiation_date")
    recalling_firm = get_text(record, "recalling_firm")

    combined = f"{product_description}\n{reason_for_recall}\n{code_info}".lower()

    if product_type.lower() == "drugs":
        score += 4
    else:
        score -= 5

    if query_drug_name and query_drug_name.lower() in combined:
        score += 5

    if classification == "Class I":
        score += 8
    elif classification == "Class II":
        score += 5
    elif classification == "Class III":
        score += 2

    if status:
        score += 1

    if status.lower() in {"ongoing", "terminated"}:
        score += 1

    if recall_number:
        score += 2

    if event_id:
        score += 1

    if recall_initiation_date:
        score += 1

    if product_description:
        score += 3

    if reason_for_recall:
        score += 4

    if product_quantity:
        score += 1

    if code_info:
        score += 2

    if distribution_pattern:
        score += 1

    if recalling_firm:
        score += 1

    reason_category = infer_reason_category(reason_for_recall)
    if reason_category != "other":
        score += 2

    noisy_terms = [
        "training only",
        "trainer",
        "not for human use",
        "homeopathic",
        "dietary supplement",
        "cosmetic",
        "animal",
    ]

    if any(term in combined for term in noisy_terms):
        score -= 8

    return score


def rank_recall_records(
    results: list[dict[str, Any]],
    query_drug_name: str | None = None,
) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}

    for record in results:
        recall_key = make_recall_key(record)
        if not recall_key:
            continue

        existing = deduped.get(recall_key)
        if existing is None:
            deduped[recall_key] = record
            continue

        if score_recall_record(record, query_drug_name) > score_recall_record(
            existing,
            query_drug_name,
        ):
            deduped[recall_key] = record

    return sorted(
        deduped.values(),
        key=lambda record: score_recall_record(record, query_drug_name),
        reverse=True,
    )


def save_raw_record(record: dict[str, Any], document_id: str) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    path = RAW_DIR / f"{document_id}.json"
    path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return path


def recall_record_to_markdown(
    record: dict[str, Any],
    fallback_drug_name: str,
) -> str:
    status = get_text(record, "status")
    city = get_text(record, "city")
    state = get_text(record, "state")
    country = get_text(record, "country")
    classification = get_text(record, "classification")
    product_type = get_text(record, "product_type")
    event_id = get_text(record, "event_id")
    recalling_firm = get_text(record, "recalling_firm")
    voluntary_mandated = get_text(record, "voluntary_mandated")
    initial_firm_notification = get_text(record, "initial_firm_notification")
    distribution_pattern = get_text(record, "distribution_pattern")
    recall_number = get_text(record, "recall_number")
    product_description = get_text(record, "product_description")
    product_quantity = get_text(record, "product_quantity")
    reason_for_recall = get_text(record, "reason_for_recall")
    recall_initiation_date = get_text(record, "recall_initiation_date")
    center_classification_date = get_text(record, "center_classification_date")
    termination_date = get_text(record, "termination_date")
    report_date = get_text(record, "report_date")
    code_info = get_text(record, "code_info")
    more_code_info = get_text(record, "more_code_info")

    normalized_drug_name = normalize_drug_name(fallback_drug_name)
    document_id = make_document_id(record, fallback_drug_name=fallback_drug_name)

    combined_text = f"{product_description}\n{code_info}\n{more_code_info}"
    ndc = extract_ndc(combined_text)
    lot = extract_lot(combined_text)
    reason_category = infer_reason_category(reason_for_recall)

    recall_initiation_date_iso = normalize_date_yyyymmdd(recall_initiation_date)
    center_classification_date_iso = normalize_date_yyyymmdd(center_classification_date)
    termination_date_iso = normalize_date_yyyymmdd(termination_date)
    report_date_iso = normalize_date_yyyymmdd(report_date)

    location_parts = [part for part in [city, state, country] if part]
    location = ", ".join(location_parts)

    lines = [
        "---",
        f"document_id: {yaml_quote(document_id)}",
        "document_type: recall_notice",
        "event_type: recall",
        f"drug_name: {yaml_quote(normalized_drug_name)}",
        f"normalized_drug_name: {yaml_quote(normalized_drug_name)}",
        f"classification: {yaml_quote(classification)}",
        f"reason_category: {yaml_quote(reason_category)}",
        f"recall_number: {yaml_quote(recall_number)}",
        f"event_id: {yaml_quote(event_id)}",
        f"status: {yaml_quote(status)}",
        f"product_type: {yaml_quote(product_type)}",
        f"recalling_firm: {yaml_quote(recalling_firm)}",
        f"voluntary_mandated: {yaml_quote(voluntary_mandated)}",
        f"initial_firm_notification: {yaml_quote(initial_firm_notification)}",
        f"recall_initiation_date: {yaml_quote(recall_initiation_date)}",
        f"recall_initiation_date_iso: {yaml_quote(recall_initiation_date_iso)}",
        f"center_classification_date: {yaml_quote(center_classification_date)}",
        f"center_classification_date_iso: {yaml_quote(center_classification_date_iso)}",
        f"termination_date: {yaml_quote(termination_date)}",
        f"termination_date_iso: {yaml_quote(termination_date_iso)}",
        f"report_date: {yaml_quote(report_date)}",
        f"report_date_iso: {yaml_quote(report_date_iso)}",
        f"ndc: {yaml_quote(ndc)}",
        f"lot: {yaml_quote(lot)}",
        "source: openFDA drug enforcement API",
        f"source_record_id: {yaml_quote(event_id)}",
        "version: v1",
        "---",
        "",
        f"# {normalized_drug_name.title()} Recall Notice",
        "",
        "## source_summary",
        f"Recall number: {recall_number or 'unknown'}",
        f"Event ID: {event_id or 'unknown'}",
        f"Classification: {classification or 'unknown'}",
        f"Reason category: {reason_category}",
        f"Status: {status or 'unknown'}",
        f"Product type: {product_type or 'unknown'}",
        f"Recalling firm: {recalling_firm or 'unknown'}",
        f"Location: {location or 'unknown'}",
        f"Recall initiation date: {recall_initiation_date_iso or recall_initiation_date or 'unknown'}",
        f"Report date: {report_date_iso or report_date or 'unknown'}",
        "",
        "## affected_product",
        product_description or "No product description provided.",
        "",
        "## reason_for_recall",
        reason_for_recall or "No recall reason provided.",
        "",
        "## product_quantity",
        product_quantity or "No product quantity provided.",
        "",
        "## code_info",
        code_info or "No code or lot information provided.",
        "",
    ]

    if more_code_info:
        lines.extend(
            [
                "## more_code_info",
                more_code_info,
                "",
            ]
        )

    lines.extend(
        [
            "## distribution_pattern",
            distribution_pattern or "No distribution pattern provided.",
            "",
            "## firm_and_notification",
            f"Recalling firm: {recalling_firm or 'unknown'}",
            f"Voluntary or mandated: {voluntary_mandated or 'unknown'}",
            f"Initial firm notification: {initial_firm_notification or 'unknown'}",
            "",
            "## dates",
            f"Recall initiation date: {recall_initiation_date_iso or recall_initiation_date or 'unknown'}",
            f"Center classification date: {center_classification_date_iso or center_classification_date or 'unknown'}",
            f"Termination date: {termination_date_iso or termination_date or 'unknown'}",
            f"Report date: {report_date_iso or report_date or 'unknown'}",
            "",
        ]
    )

    return "\n".join(lines).strip() + "\n"


def save_markdown(record: dict[str, Any], drug_name: str) -> Path:
    DOC_DIR.mkdir(parents=True, exist_ok=True)

    document_id = make_document_id(record, fallback_drug_name=drug_name)
    path = DOC_DIR / f"{document_id}.md"

    path.write_text(
        recall_record_to_markdown(record, fallback_drug_name=drug_name),
        encoding="utf-8",
    )

    return path


def save_record_if_valid(
    record: dict[str, Any],
    drug_name: str,
    seen_recall_keys: set[str],
    source_mode: str,
    query_drug_name: str | None = None,
) -> tuple[bool, str]:
    recall_key = make_recall_key(record)
    if not recall_key:
        return False, "missing_recall_key"

    if recall_key in seen_recall_keys:
        return False, "duplicate"

    score = score_recall_record(record, query_drug_name=query_drug_name)
    if score < MIN_RECORD_SCORE:
        return False, f"low_score_{score}"

    document_id = make_document_id(record, fallback_drug_name=drug_name)

    save_raw_record(record, document_id=document_id)
    md_path = save_markdown(record, drug_name=drug_name)

    seen_recall_keys.add(recall_key)

    print(
        f"[OK] Saved recall document: {md_path.name} "
        f"(score={score}, drug={drug_name}, mode={source_mode})"
    )

    return True, "saved"


def targeted_fetch(
    seen_recall_keys: set[str],
    total_saved: int,
) -> tuple[int, int, int]:
    saved = 0
    skipped = 0
    failed = 0

    for drug_name in DRUG_NAMES:
        if total_saved + saved >= TARGET_RECALL_DOCUMENTS:
            break

        try:
            payload = fetch_recalls_by_drug(drug_name, limit=API_LIMIT_PER_DRUG)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                print(f"[WARN] No recall records found for {drug_name}")
                skipped += 1
                continue

            print(f"[WARN] Failed to fetch recall records for {drug_name}: {exc}")
            failed += 1
            continue
        except httpx.RequestError as exc:
            print(
                f"[WARN] Request error while fetching recall records for "
                f"{drug_name}: {exc}"
            )
            failed += 1
            continue

        results = payload.get("results", [])
        if not isinstance(results, list) or not results:
            print(f"[WARN] No recall records found for {drug_name}")
            skipped += 1
            continue

        ranked_records = rank_recall_records(results, query_drug_name=drug_name)
        saved_for_drug = 0

        for record in ranked_records:
            if saved_for_drug >= MAX_RECORDS_PER_DRUG:
                break
            if total_saved + saved >= TARGET_RECALL_DOCUMENTS:
                break

            ok, reason = save_record_if_valid(
                record=record,
                drug_name=drug_name,
                seen_recall_keys=seen_recall_keys,
                source_mode="targeted",
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
    seen_recall_keys: set[str],
    total_saved: int,
) -> tuple[int, int, int]:
    saved = 0
    skipped = 0
    failed = 0

    if total_saved >= TARGET_RECALL_DOCUMENTS:
        return saved, skipped, failed

    print()
    print("[INFO] Starting broad recall backfill...")

    for query in BROAD_RECALL_QUERIES:
        if total_saved + saved >= TARGET_RECALL_DOCUMENTS:
            break

        for page in range(BROAD_FETCH_PAGES):
            if total_saved + saved >= TARGET_RECALL_DOCUMENTS:
                break

            skip = page * BROAD_FETCH_LIMIT

            try:
                payload = fetch_recalls_by_query(
                    query=query,
                    limit=BROAD_FETCH_LIMIT,
                    skip=skip,
                )
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
                if total_saved + saved >= TARGET_RECALL_DOCUMENTS:
                    break

                inferred_drug_name = infer_drug_name_from_recall(record)

                ok, reason = save_record_if_valid(
                    record=record,
                    drug_name=inferred_drug_name,
                    seen_recall_keys=seen_recall_keys,
                    source_mode="broad",
                    query_drug_name=None,
                )

                if ok:
                    saved += 1
                else:
                    skipped += 1
                    if reason not in {"duplicate", "low_score_0"}:
                        pass

    return saved, skipped, failed


def main() -> None:
    seen_recall_keys: set[str] = set()

    targeted_saved, targeted_skipped, targeted_failed = targeted_fetch(
        seen_recall_keys=seen_recall_keys,
        total_saved=0,
    )

    broad_saved, broad_skipped, broad_failed = broad_backfill(
        seen_recall_keys=seen_recall_keys,
        total_saved=targeted_saved,
    )

    total_saved = targeted_saved + broad_saved
    total_skipped = targeted_skipped + broad_skipped
    total_failed = targeted_failed + broad_failed

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
