from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml
from dotenv import load_dotenv
from scripts.rag.common import slugify as base_slugify


ROOT_DIR = Path(__file__).resolve().parents[3]
RAG_DIR = ROOT_DIR / "data" / "rag"
PROCESSED_DIR = RAG_DIR / "processed"
DEFAULT_DRUG_LIST_PATH = Path(__file__).with_name("drugs.yaml")
MANIFEST_PATH = PROCESSED_DIR / "openfda_fetch_manifest.json"


def slugify(value: str, max_length: int = 80) -> str:
    return base_slugify(value, max_length=max_length, separator="_")


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
    return json.dumps(value or "", ensure_ascii=False)


def yaml_nullable(value: str | None) -> str:
    if value is None or not str(value).strip():
        return "null"
    return json.dumps(str(value), ensure_ascii=False)


def normalize_drug_name(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"\s+", " ", value)
    return value or "unknown"


def get_text(record: dict[str, Any], field: str) -> str:
    value = record.get(field, "")
    if value is None:
        return ""
    return clean_text(str(value))


def normalize_date_yyyymmdd(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r"\d{8}", value):
        return f"{value[:4]}-{value[4:6]}-{value[6:8]}"
    return ""


def load_drug_names(
    path: Path = DEFAULT_DRUG_LIST_PATH,
    profile: str | None = None,
) -> list[str]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    names: list[str] = []

    if profile is not None and isinstance(payload, dict):
        if profile not in payload:
            raise ValueError(f"Drug list YAML is missing the '{profile}' group.")
        payload = payload[profile]
    if isinstance(payload, list):
        candidates = payload
    elif isinstance(payload, dict):
        candidates = []
        for value in payload.values():
            if isinstance(value, list):
                candidates.extend(value)
            else:
                raise ValueError(f"Drug list group must be a list: {value!r}")
    else:
        raise ValueError("Drug list YAML must contain a list or mapping of lists.")

    seen: set[str] = set()
    for item in candidates:
        name = str(item).strip()
        key = name.lower()
        if name and key not in seen:
            names.append(name)
            seen.add(key)

    return names


def fetch_openfda_json(base_url: str, params: dict[str, Any]) -> dict[str, Any]:
    load_dotenv()

    api_key = os.getenv("OPENFDA_API_KEY")
    if api_key:
        params = {**params, "api_key": api_key}

    with httpx.Client(timeout=30.0) as client:
        response = client.get(base_url, params=params)
        response.raise_for_status()
        return response.json()


def write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def save_raw_record(raw_dir: Path, record: dict[str, Any], document_id: str) -> Path:
    return write_json(raw_dir / f"{document_id}.json", record)


def clean_markdown_dir(
    doc_dir: Path,
    retries: int = 3,
    delay_seconds: float = 0.25,
) -> None:
    if not doc_dir.exists():
        return

    for existing_path in doc_dir.glob("*.md"):
        for attempt in range(retries + 1):
            try:
                existing_path.unlink()
                break
            except PermissionError:
                if attempt >= retries:
                    raise
                time.sleep(delay_seconds * (attempt + 1))


def write_fetch_manifest(kind: str, payload: dict[str, Any]) -> Path:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {}

    if MANIFEST_PATH.exists():
        existing = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        if isinstance(existing, dict):
            manifest = existing

    manifest[kind] = {
        **payload,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    return write_json(MANIFEST_PATH, manifest)
