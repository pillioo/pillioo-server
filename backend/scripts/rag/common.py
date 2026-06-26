from __future__ import annotations

import json
import re
import textwrap
from pathlib import Path
from typing import Any

import yaml


def load_yaml_documents(path: Path, document_label: str) -> list[dict[str, Any]]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))

    if not isinstance(payload, list):
        raise ValueError(f"{document_label} fixture file must contain a list of documents.")

    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(f"{document_label} fixture at index {index} must be an object.")

    return payload


def slugify(value: str, max_length: int = 90, separator: str = "-") -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", separator, value)
    value = value.strip(separator) or "unknown"
    return value[:max_length].strip(separator) or "unknown"


def yaml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"

    if isinstance(value, list):
        return "[" + ", ".join(json.dumps(item, ensure_ascii=False) for item in value) + "]"

    return json.dumps(str(value), ensure_ascii=False)


def normalize_block(value: str) -> str:
    return textwrap.dedent(value).strip()
