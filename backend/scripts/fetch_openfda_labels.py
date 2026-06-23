from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv


BASE_URL = "https://api.fda.gov/drug/label.json"

ROOT_DIR = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT_DIR / "data" / "rag" / "raw" / "openfda" / "label"
DOC_DIR = ROOT_DIR / "data" / "rag" / "documents" / "label"

API_LIMIT_PER_DRUG = 10
MAX_RECORDS_PER_DRUG = 2
TARGET_LABEL_DOCUMENTS = 60
MIN_RECORD_SCORE = 8


DRUG_NAMES = [
    # Sedation / anesthesia / analgesics
    "midazolam",
    "propofol",
    "fentanyl",
    "morphine sulfate",
    "hydromorphone",
    "ketamine",
    "dexmedetomidine",
    "bupivacaine hydrochloride",
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
    "piperacillin and tazobactam",
    "meropenem",

    # Anticoagulants / cardiovascular
    "heparin sodium",
    "enoxaparin sodium",
    "warfarin sodium",
    "alteplase",
    "amiodarone",
    "nitroglycerin",

    # Endocrine / metabolic
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


SECTION_SOURCES: list[tuple[str, list[str]]] = [
    ("boxed_warning", ["boxed_warning"]),
    ("warnings", ["warnings", "warnings_and_cautions"]),
    ("contraindications", ["contraindications"]),
    ("indications_and_usage", ["indications_and_usage"]),
    ("dosage_and_administration", ["dosage_and_administration"]),
    ("dosage_forms_and_strengths", ["dosage_forms_and_strengths"]),
    ("adverse_reactions", ["adverse_reactions"]),
    ("drug_interactions", ["drug_interactions"]),
    ("use_in_specific_populations", ["use_in_specific_populations"]),
    ("overdosage", ["overdosage"]),
    ("description", ["description"]),
    ("clinical_pharmacology", ["clinical_pharmacology"]),
    ("mechanism_of_action", ["mechanism_of_action"]),
    ("pharmacodynamics", ["pharmacodynamics"]),
    ("pharmacokinetics", ["pharmacokinetics"]),
    ("how_supplied", ["how_supplied"]),
    ("storage_and_handling", ["storage_and_handling"]),
    ("information_for_patients", ["information_for_patients"]),
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


def first(value: Any, default: str = "") -> str:
    if isinstance(value, list) and value:
        return str(value[0])
    if isinstance(value, str):
        return value
    return default


def as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def yaml_quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def normalize_drug_name(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"\s+", " ", value)
    return value


def get_openfda(record: dict[str, Any]) -> dict[str, Any]:
    openfda = record.get("openfda")
    if isinstance(openfda, dict):
        return openfda
    return {}


def get_generic_name(record: dict[str, Any], fallback_name: str = "unknown") -> str:
    openfda = get_openfda(record)
    generic_name = first(openfda.get("generic_name"), "")
    if generic_name:
        return generic_name

    active_ingredient = first(record.get("active_ingredient"), "")
    if active_ingredient:
        return active_ingredient

    return fallback_name


def get_brand_name(record: dict[str, Any], fallback_name: str = "unknown") -> str:
    openfda = get_openfda(record)
    return first(openfda.get("brand_name"), fallback_name)


def get_record_identifier(record: dict[str, Any]) -> str:
    openfda = get_openfda(record)

    set_id = str(record.get("set_id") or "")
    spl_id = first(openfda.get("spl_id"), "")
    record_id = str(record.get("id") or "")

    return set_id or spl_id or record_id or "unknown"


def make_document_id(record: dict[str, Any], fallback_name: str) -> str:
    generic_name = get_generic_name(record, fallback_name=fallback_name)
    identifier = get_record_identifier(record)

    drug_slug = slugify(generic_name, max_length=50)
    id_slug = slugify(identifier, max_length=40)

    return f"label-{drug_slug}-{id_slug}"


def get_section_text(record: dict[str, Any], source_fields: list[str]) -> str:
    parts: list[str] = []

    for field in source_fields:
        values = as_list(record.get(field))
        for value in values:
            cleaned = clean_text(value)
            if cleaned:
                parts.append(cleaned)

    return "\n\n".join(parts).strip()


def get_included_sections(record: dict[str, Any]) -> list[str]:
    included: list[str] = []

    for canonical_section, source_fields in SECTION_SOURCES:
        if get_section_text(record, source_fields):
            included.append(canonical_section)

    return included


def score_label_record(record: dict[str, Any]) -> int:
    score = 0
    openfda = get_openfda(record)

    product_types = [item.upper() for item in as_list(openfda.get("product_type"))]
    routes = [item.upper() for item in as_list(openfda.get("route"))]

    if openfda:
        score += 4
    else:
        score -= 5

    if "HUMAN PRESCRIPTION DRUG" in product_types:
        score += 6

    if any(
        route in routes
        for route in [
            "INTRAVENOUS",
            "INTRAMUSCULAR",
            "SUBCUTANEOUS",
            "EPIDURAL",
            "INFILTRATION",
            "PERINEURAL",
            "INTRACAUDAL",
        ]
    ):
        score += 3

    section_weights = {
        "boxed_warning": 5,
        "warnings": 4,
        "contraindications": 4,
        "dosage_and_administration": 3,
        "adverse_reactions": 3,
        "drug_interactions": 3,
        "use_in_specific_populations": 2,
        "overdosage": 2,
        "clinical_pharmacology": 1,
        "how_supplied": 1,
    }

    for section, weight in section_weights.items():
        source_fields = next(
            fields for canonical, fields in SECTION_SOURCES if canonical == section
        )
        if get_section_text(record, source_fields):
            score += weight

    if openfda.get("generic_name"):
        score += 2
    if openfda.get("brand_name"):
        score += 1
    if openfda.get("product_ndc"):
        score += 1
    if record.get("effective_time"):
        score += 1

    total_chars = sum(
        len(get_section_text(record, source_fields))
        for _, source_fields in SECTION_SOURCES
    )
    score += min(total_chars // 3000, 5)

    return score


def fetch_label_payload(drug_name: str, limit: int = API_LIMIT_PER_DRUG) -> dict[str, Any]:
    load_dotenv()

    params: dict[str, Any] = {
        "search": (
            f'openfda.generic_name:"{drug_name}" '
            f'OR openfda.brand_name:"{drug_name}" '
            f'OR openfda.substance_name:"{drug_name}" '
            f'OR active_ingredient:"{drug_name}"'
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


def rank_label_records(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}

    for record in results:
        identifier = get_record_identifier(record)
        if identifier == "unknown":
            continue

        existing = deduped.get(identifier)
        if existing is None or score_label_record(record) > score_label_record(existing):
            deduped[identifier] = record

    return sorted(deduped.values(), key=score_label_record, reverse=True)


def save_raw_record(record: dict[str, Any], document_id: str) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    path = RAW_DIR / f"{document_id}.json"
    path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return path


def label_record_to_markdown(record: dict[str, Any], fallback_name: str) -> str:
    openfda = get_openfda(record)

    generic_name = get_generic_name(record, fallback_name=fallback_name)
    brand_name = get_brand_name(record, fallback_name=generic_name)
    normalized_drug_name = normalize_drug_name(generic_name)

    product_ndc = as_list(openfda.get("product_ndc"))
    package_ndc = as_list(openfda.get("package_ndc"))
    route = as_list(openfda.get("route"))
    product_type = first(openfda.get("product_type"), "")
    manufacturer_name = first(openfda.get("manufacturer_name"), "")

    set_id = str(record.get("set_id") or "")
    spl_id = first(openfda.get("spl_id"), str(record.get("id") or ""))
    effective_time = str(record.get("effective_time") or "")
    version = str(record.get("version") or "v1")

    document_id = make_document_id(record, fallback_name=fallback_name)
    included_sections = get_included_sections(record)

    lines = [
        "---",
        f"document_id: {yaml_quote(document_id)}",
        "document_type: label",
        "event_type: label_update",
        f"drug_name: {yaml_quote(normalized_drug_name)}",
        f"normalized_drug_name: {yaml_quote(normalized_drug_name)}",
        f"brand_name: {yaml_quote(brand_name)}",
        f"product_ndc: {json.dumps(product_ndc, ensure_ascii=False)}",
        f"package_ndc: {json.dumps(package_ndc, ensure_ascii=False)}",
        f"route: {json.dumps(route, ensure_ascii=False)}",
        f"product_type: {yaml_quote(product_type)}",
        f"manufacturer_name: {yaml_quote(manufacturer_name)}",
        f"set_id: {yaml_quote(set_id)}",
        f"spl_id: {yaml_quote(spl_id)}",
        f"effective_time: {yaml_quote(effective_time)}",
        "source: openFDA drug label API",
        f"source_record_id: {yaml_quote(str(record.get('id') or ''))}",
        f"included_sections: {json.dumps(included_sections, ensure_ascii=False)}",
        f"version: {yaml_quote(version)}",
        "---",
        "",
        f"# {generic_name} Label",
        "",
        "## source_summary",
        f"Generic name: {generic_name}",
        f"Brand name: {brand_name}",
        f"Product NDC: {', '.join(product_ndc) if product_ndc else 'unknown'}",
        f"Route: {', '.join(route) if route else 'unknown'}",
        f"Manufacturer: {manufacturer_name or 'unknown'}",
        f"Effective time: {effective_time or 'unknown'}",
        "",
    ]

    for canonical_section, source_fields in SECTION_SOURCES:
        text = get_section_text(record, source_fields)
        if not text:
            continue

        lines.extend(
            [
                f"## {canonical_section}",
                text,
                "",
            ]
        )

    return "\n".join(lines).strip() + "\n"


def save_markdown(record: dict[str, Any], fallback_name: str) -> Path:
    DOC_DIR.mkdir(parents=True, exist_ok=True)

    document_id = make_document_id(record, fallback_name=fallback_name)
    path = DOC_DIR / f"{document_id}.md"
    path.write_text(
        label_record_to_markdown(record, fallback_name=fallback_name),
        encoding="utf-8",
    )

    return path


def main() -> None:
    total_saved = 0
    total_skipped = 0
    total_failed = 0
    seen_document_ids: set[str] = set()

    for drug_name in DRUG_NAMES:
        if total_saved >= TARGET_LABEL_DOCUMENTS:
            break

        try:
            payload = fetch_label_payload(drug_name, limit=API_LIMIT_PER_DRUG)
        except httpx.HTTPStatusError as exc:
            print(f"[WARN] Failed to fetch label for {drug_name}: {exc}")
            total_failed += 1
            continue
        except httpx.RequestError as exc:
            print(f"[WARN] Request error while fetching label for {drug_name}: {exc}")
            total_failed += 1
            continue

        results = payload.get("results", [])
        if not isinstance(results, list) or not results:
            print(f"[WARN] No label found for {drug_name}")
            total_skipped += 1
            continue

        ranked_records = rank_label_records(results)
        saved_for_drug = 0

        for record in ranked_records:
            if saved_for_drug >= MAX_RECORDS_PER_DRUG:
                break
            if total_saved >= TARGET_LABEL_DOCUMENTS:
                break

            score = score_label_record(record)
            if score < MIN_RECORD_SCORE:
                total_skipped += 1
                continue

            document_id = make_document_id(record, fallback_name=drug_name)
            if document_id in seen_document_ids:
                total_skipped += 1
                continue

            save_raw_record(record, document_id=document_id)
            md_path = save_markdown(record, fallback_name=drug_name)

            seen_document_ids.add(document_id)
            saved_for_drug += 1
            total_saved += 1

            print(
                f"[OK] Saved label document: {md_path.name} "
                f"(score={score}, drug={drug_name})"
            )

        if saved_for_drug == 0:
            print(f"[WARN] No high-quality label selected for {drug_name}")

    print()
    print("[SUMMARY]")
    print(f"saved={total_saved}")
    print(f"skipped={total_skipped}")
    print(f"failed={total_failed}")
    print(f"raw_dir={RAW_DIR}")
    print(f"doc_dir={DOC_DIR}")


if __name__ == "__main__":
    main()
