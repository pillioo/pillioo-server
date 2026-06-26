from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.rag.common import load_yaml_documents


SOP_DOCUMENTS_PATH = Path(__file__).with_name("sop_documents.yaml")


def load_sop_documents(path: Path = SOP_DOCUMENTS_PATH) -> list[dict[str, Any]]:
    return load_yaml_documents(path, "SOP")


SOP_DOCUMENTS = load_sop_documents()
