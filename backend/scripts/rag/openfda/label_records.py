from __future__ import annotations

import json
import re
from typing import Any

from scripts.rag.openfda.common import (
    as_list,
    clean_text,
    first,
    normalize_drug_name,
    slugify,
    yaml_quote,
)


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

# These tokens are ignored when matching the query drug so salt/form variants
# still group together, but the core ingredient must remain present.
SALT_OR_FORM_TOKENS = {
    "anhydrous",
    "bitartrate",
    "citrate",
    "dextrose",
    "hbr",
    "hcl",
    "hydrochloride",
    "hydrate",
    "human",
    "monohydrate",
    "sodium",
    "sulfate",
}

LABEL_NOISY_TERMS = {
    "cold and flu",
    "cough plus cold",
    "dietary supplement",
    "homeopathic",
    "kit",
    "meridian opener",
}


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


def normalize_match_text(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def get_query_tokens(drug_name: str) -> list[str]:
    tokens = normalize_match_text(drug_name).split()
    core_tokens = [token for token in tokens if token not in SALT_OR_FORM_TOKENS]
    return core_tokens or tokens


def field_contains_query(value: Any, query_tokens: list[str]) -> bool:
    values = as_list(value)
    for item in values:
        normalized = normalize_match_text(item)
        if all(re.search(rf"\b{re.escape(token)}\b", normalized) for token in query_tokens):
            return True
    return False


def get_label_query_match_fields(
    record: dict[str, Any],
    query_drug_name: str,
) -> list[str]:
    # openFDA can return rich labels that only mention the query drug as a
    # secondary ingredient; tracking the matched field makes that auditable.
    openfda = get_openfda(record)
    query_tokens = get_query_tokens(query_drug_name)
    match_fields: list[str] = []

    for field_name, value in [
        ("generic_name", openfda.get("generic_name")),
        ("brand_name", openfda.get("brand_name")),
        ("substance_name", openfda.get("substance_name")),
        ("active_ingredient", record.get("active_ingredient")),
    ]:
        if field_contains_query(value, query_tokens):
            match_fields.append(field_name)

    return match_fields


def has_noisy_label_terms(record: dict[str, Any]) -> bool:
    openfda = get_openfda(record)
    searchable_parts = [
        get_generic_name(record, fallback_name=""),
        get_brand_name(record, fallback_name=""),
        first(openfda.get("product_type"), ""),
        get_section_text(record, ["indications_and_usage"]),
    ]
    searchable = normalize_match_text(" ".join(searchable_parts))
    return any(term in searchable for term in LABEL_NOISY_TERMS)


def has_broad_combination_name(record: dict[str, Any]) -> bool:
    # Large kits and multi-product bundles tend to score well on section
    # richness, but they are weak standalone RAG evidence for a single drug.
    generic_name = get_generic_name(record, fallback_name="").lower()
    if not generic_name:
        return False

    separators = len(re.findall(r"\b(?:and|with)\b|,", generic_name))
    return separators >= 3


def is_secondary_combination_match(
    record: dict[str, Any],
    query_drug_name: str,
) -> bool:
    # For single-token drugs, avoid saving labels where the drug only appears
    # after "and/with" in a combination product name.
    query_tokens = get_query_tokens(query_drug_name)
    if len(query_tokens) != 1:
        return False

    generic_name = get_generic_name(record, fallback_name="").lower()
    if not re.search(r"\b(?:and|with)\b|,", generic_name):
        return False

    primary_part = re.split(r"\b(?:and|with)\b|,", generic_name, maxsplit=1)[0]
    normalized_primary = normalize_match_text(primary_part)
    return not re.search(rf"\b{re.escape(query_tokens[0])}\b", normalized_primary)


def score_label_record(
    record: dict[str, Any],
    query_drug_name: str | None = None,
) -> int:
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

    if query_drug_name:
        match_fields = get_label_query_match_fields(record, query_drug_name)
        if "generic_name" in match_fields or "brand_name" in match_fields:
            score += 10
        elif match_fields:
            score += 2
        else:
            score -= 25

    if has_noisy_label_terms(record):
        score -= 35

    if has_broad_combination_name(record):
        score -= 25

    if query_drug_name and is_secondary_combination_match(record, query_drug_name):
        score -= 30

    total_chars = sum(
        len(get_section_text(record, source_fields))
        for _, source_fields in SECTION_SOURCES
    )
    score += min(total_chars // 3000, 5)

    return score


def rank_label_records(
    results: list[dict[str, Any]],
    query_drug_name: str | None = None,
) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}

    for record in results:
        identifier = get_record_identifier(record)
        if identifier == "unknown":
            continue

        existing = deduped.get(identifier)
        if existing is None or score_label_record(
            record,
            query_drug_name=query_drug_name,
        ) > score_label_record(existing, query_drug_name=query_drug_name):
            deduped[identifier] = record

    return sorted(
        deduped.values(),
        key=lambda record: score_label_record(record, query_drug_name=query_drug_name),
        reverse=True,
    )


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
        f"openfda_query_drug: {yaml_quote(normalize_drug_name(fallback_name))}",
        f"query_match_fields: {json.dumps(get_label_query_match_fields(record, fallback_name), ensure_ascii=False)}",
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

        lines.extend([f"## {canonical_section}", text, ""])

    return "\n".join(lines).strip() + "\n"