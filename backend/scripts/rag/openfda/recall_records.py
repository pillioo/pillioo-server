from __future__ import annotations

import re
from typing import Any

from scripts.rag.identity.rxnorm_client import get_best_cached_drug_identity
from scripts.rag.openfda.common import (
    get_text,
    normalize_date_yyyymmdd,
    normalize_drug_name,
    slugify,
    yaml_nullable,
    yaml_quote,
)


NOISY_TERMS = [
    "training only",
    "trainer",
    "not for human use",
    "homeopathic",
    "dietary supplement",
    "vitamin supplement",
    "cold, flu",
    "cough suppressant",
    "dextromethorphan",
    "guaifenesin",
    "hand sanitizer",
    "hand sanitizing",
    "root powder",
    "oral spray",
    "kratom",
    "detox",
    "cosmetic",
    "animal",
    "alka-seltzer",
    "carboxymethylcellulose",
    "coupon",
    "dr king",
    "dr. king",
    "dry eye",
    "eye relief",
    "homeopathic principles",
    "king bio",
    "liothyronine thyroid",
    "mucinex",
    "neonate",
    "np thyroid",
    "safecare",
    "sinus spray",
    "sore throat",
    "thyroid",
    "trophamine",
    "tpn neonatal",
    "water retention",
]

# Stopwords keep broad matching from treating salts/routes as the ingredient,
# while still requiring the clinically relevant token to appear.
DRUG_MATCH_STOPWORDS = {
    "and",
    "for",
    "hbr",
    "hcl",
    "human",
    "hydrochloride",
    "in",
    "sulfate",
    "the",
    "with",
}


def extract_ndc(text: str) -> str:
    match = re.search(r"\b\d{4,5}-\d{3,4}-\d{1,2}\b", text)
    return match.group(0) if match else ""


def extract_lots(text: str) -> list[str]:
    if re.search(r"\ball\s+(?:lot\s+codes|lots?|codes?)\b", text, flags=re.IGNORECASE):
        return ["all_lots"]

    candidates: list[str] = []
    patterns = [
        r"(?:lot|lot number|lot no\.?|lot #|lots?)[:\s#-]+([A-Z0-9][A-Z0-9,\s;/.-]{1,120})",
        r"\bLot\s+([A-Z0-9-]{2,})\b",
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            raw_value = re.sub(
                r"\b(exp|expires?|expiration|no expiration date).*$",
                "",
                match.group(1),
                flags=re.IGNORECASE,
            )
            parts = re.split(r"[,;/]|\band\b", raw_value, flags=re.IGNORECASE)
            for part in parts:
                value = re.sub(r"[^A-Za-z0-9-]", "", part).strip("-")
                if len(value) >= 2:
                    candidates.append(value)

    seen: set[str] = set()
    lots: list[str] = []
    for value in candidates:
        key = value.upper()
        if key not in seen:
            lots.append(value)
            seen.add(key)

    return lots


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


def get_noisy_terms(record: dict[str, Any]) -> list[str]:
    product_description = get_text(record, "product_description")
    reason_for_recall = get_text(record, "reason_for_recall")
    code_info = get_text(record, "code_info")
    combined = f"{product_description}\n{reason_for_recall}\n{code_info}".lower()
    return [term for term in NOISY_TERMS if term in combined]


def normalize_match_text(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def get_drug_match_tokens(drug_name: str) -> list[str]:
    tokens = normalize_match_text(drug_name).split()
    core_tokens = [token for token in tokens if token not in DRUG_MATCH_STOPWORDS]
    return core_tokens or tokens


def recall_matches_drug_name(
    record: dict[str, Any],
    drug_name: str,
    *,
    product_only: bool = False,
    primary_only: bool = False,
) -> bool:
    # Broad backfill is intentionally stricter than targeted search: product
    # names like "calcium gluconate in sodium chloride" should not become a
    # sodium chloride recall just because the vehicle is mentioned.
    product_description = get_text(record, "product_description")
    reason_for_recall = get_text(record, "reason_for_recall")
    code_info = get_text(record, "code_info")
    searchable_source = (
        product_description
        if product_only
        else f"{product_description} {reason_for_recall} {code_info}"
    )
    searchable = normalize_match_text(searchable_source)
    tokens = get_drug_match_tokens(drug_name)
    if not all(re.search(rf"\b{re.escape(token)}\b", searchable) for token in tokens):
        return False

    if not primary_only or len(tokens) != 1:
        return True

    primary_part = re.split(
        r"\b(?:added to|and|in|with)\b|/",
        product_description.lower(),
        maxsplit=1,
    )[0]
    normalized_primary = normalize_match_text(primary_part)
    return bool(re.search(rf"\b{re.escape(tokens[0])}\b", normalized_primary))


def get_matching_drug_names(
    record: dict[str, Any],
    drug_names: list[str],
    *,
    product_only: bool = False,
    primary_only: bool = False,
) -> list[str]:
    return [
        drug_name
        for drug_name in drug_names
        if recall_matches_drug_name(
            record,
            drug_name,
            product_only=product_only,
            primary_only=primary_only,
        )
    ]


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

    head = product_description.split(",")[0]
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

    noisy_hits = get_noisy_terms(record)
    if noisy_hits:
        score -= 30 + (len(noisy_hits) - 1) * 6

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

        if score_recall_record(record, query_drug_name) > score_recall_record(existing, query_drug_name):
            deduped[recall_key] = record

    return sorted(
        deduped.values(),
        key=lambda record: score_recall_record(record, query_drug_name),
        reverse=True,
    )


def recall_record_to_markdown(
    record: dict[str, Any],
    fallback_drug_name: str,
    source_mode: str,
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

    fallback_normalized_drug_name = normalize_drug_name(fallback_drug_name)
    identity = get_best_cached_drug_identity([fallback_drug_name])
    normalized_drug_name = identity["normalized_drug_name"] or fallback_normalized_drug_name
    document_id = make_document_id(record, fallback_drug_name=fallback_drug_name)

    combined_text = f"{product_description}\n{code_info}\n{more_code_info}"
    ndc = extract_ndc(combined_text)
    lot_source_text = "\n".join(part for part in [code_info, more_code_info] if part)
    lots = extract_lots(lot_source_text)
    if lots == ["all_lots"]:
        lot = None
        lot_scope = "all_lots"
    elif lots:
        lot = ", ".join(lots)
        lot_scope = "specific_lots"
    else:
        lot = None
        lot_scope = "unknown"
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
        f"source_mode: {yaml_quote(source_mode)}",
        f"drug_name: {yaml_quote(normalized_drug_name)}",
        f"normalized_drug_name: {yaml_quote(normalized_drug_name)}",
        f"openfda_drug_name: {yaml_quote(fallback_normalized_drug_name)}",
        f"rxnorm_rxcui: {yaml_nullable(identity['rxnorm_rxcui'])}",
        f"rxnorm_name: {yaml_nullable(identity['rxnorm_name'])}",
        f"rxnorm_tty: {yaml_nullable(identity['rxnorm_tty'])}",
        f"drug_identity_match_basis: {yaml_quote(identity['match_basis'])}",
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
        f"ndc: {yaml_nullable(ndc)}",
        f"lot: {yaml_nullable(lot)}",
        f"lot_scope: {yaml_quote(lot_scope)}",
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
        f"Source mode: {source_mode}",
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
        lines.extend(["## more_code_info", more_code_info, ""])

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
