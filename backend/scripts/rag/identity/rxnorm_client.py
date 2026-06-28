from __future__ import annotations

import json
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx


RXNORM_BASE_URL = "https://rxnav.nlm.nih.gov/REST"
ROOT_DIR = Path(__file__).resolve().parents[3]
REFERENCE_DIR = ROOT_DIR / "data" / "reference"
DEFAULT_CACHE_PATH = REFERENCE_DIR / "drug_identity_cache.json"
MIN_APPROXIMATE_SCORE = 80


def normalize_identity_key(name: str) -> str:
    value = name.lower().strip()
    value = re.sub(r"\s+", " ", value)
    return value


def fallback_identity(name: str) -> dict[str, Any]:
    normalized_input = normalize_identity_key(name)
    return {
        "raw_name": name,
        "normalized_drug_name": normalized_input,
        "rxnorm_rxcui": None,
        "rxnorm_name": None,
        "rxnorm_tty": None,
        "rxnorm_approximate_score": None,
        "match_basis": "fallback_normalized_string",
    }


def request_json(
    path: str,
    params: dict[str, str],
    *,
    timeout: float = 10.0,
) -> dict[str, Any]:
    with httpx.Client(timeout=timeout) as client:
        response = client.get(f"{RXNORM_BASE_URL}{path}", params=params)
        response.raise_for_status()
        return response.json()


def find_rxcui_by_string(name: str) -> str | None:
    payload = request_json("/rxcui.json", {"name": name})
    candidates = payload.get("idGroup", {}).get("rxnormId", [])

    if not candidates:
        return None

    return str(candidates[0])


def get_approximate_candidate(name: str) -> dict[str, Any] | None:
    payload = request_json(
        "/approximateTerm.json",
        {
            "term": name,
            "maxEntries": "1",
        },
    )
    candidates = payload.get("approximateGroup", {}).get("candidate", [])

    if not candidates:
        return None

    candidate = candidates[0]
    rxcui = candidate.get("rxcui")
    if not rxcui:
        return None

    return {
        "rxcui": str(rxcui),
        "score": float(candidate.get("score") or 0),
    }


def get_rxconcept_properties(rxcui: str) -> dict[str, Any] | None:
    payload = request_json(f"/rxcui/{rxcui}/properties.json", {})
    properties = payload.get("properties")
    return properties if isinstance(properties, dict) else None


def resolve_drug_identity(name: str) -> dict[str, Any]:
    normalized_input = normalize_identity_key(name)
    if not normalized_input:
        return fallback_identity(name)

    rxcui = find_rxcui_by_string(normalized_input)
    match_basis = "rxnorm_exact"
    approximate_score = None

    if rxcui is None:
        candidate = get_approximate_candidate(normalized_input)
        if candidate and candidate["score"] >= MIN_APPROXIMATE_SCORE:
            rxcui = candidate["rxcui"]
            approximate_score = candidate["score"]
        match_basis = "rxnorm_approximate"

    if rxcui is None:
        return fallback_identity(name)

    properties = get_rxconcept_properties(rxcui) or {}
    if not properties:
        return fallback_identity(name)

    time.sleep(0.05)

    rxnorm_name = properties.get("name")
    return {
        "raw_name": name,
        "normalized_drug_name": normalize_identity_key(str(rxnorm_name or normalized_input)),
        "rxnorm_rxcui": rxcui,
        "rxnorm_name": rxnorm_name,
        "rxnorm_tty": properties.get("tty"),
        "rxnorm_approximate_score": approximate_score,
        "match_basis": match_basis,
    }


def load_identity_cache(path: Path = DEFAULT_CACHE_PATH) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Drug identity cache must be an object: {path}")

    return {
        normalize_identity_key(str(key)): value
        for key, value in payload.items()
        if isinstance(value, dict)
    }


def write_identity_cache(
    cache: dict[str, dict[str, Any]],
    path: Path = DEFAULT_CACHE_PATH,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized_cache = {
        normalize_identity_key(key): value
        for key, value in sorted(cache.items())
    }
    path.write_text(
        json.dumps(normalized_cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


@lru_cache(maxsize=1)
def get_default_identity_cache() -> dict[str, dict[str, Any]]:
    return load_identity_cache()


def get_cached_drug_identity(name: str) -> dict[str, Any]:
    key = normalize_identity_key(name)
    cache = get_default_identity_cache()
    return cache.get(key) or fallback_identity(name)


def get_best_cached_drug_identity(names: list[str]) -> dict[str, Any]:
    for name in names:
        key = normalize_identity_key(name)
        if not key:
            continue

        identity = get_default_identity_cache().get(key)
        if identity and identity.get("rxnorm_rxcui"):
            return identity

    fallback_name = next((name for name in names if normalize_identity_key(name)), "")
    return fallback_identity(fallback_name)
