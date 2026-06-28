from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.rag.common import load_yaml_documents


SOP_DOCUMENTS_PATH = Path(__file__).with_name("sop_documents.yaml")
REQUIRED_FIELDS = {
    "document_id",
    "sop_id",
    "title",
    "event_type",
    "priority",
    "requires_human_approval",
    "applies_to",
    "purpose",
    "trigger",
    "required_inputs",
    "procedure",
    "exception_handling",
    "completion_criteria",
}
VALID_EVENT_TYPES = {"recall", "shortage", "label_update"}


def load_sop_documents(path: Path = SOP_DOCUMENTS_PATH) -> list[dict[str, Any]]:
    documents = load_yaml_documents(path, "SOP")

    for document in documents:
        document_id = str(document.get("document_id") or "<unknown>")
        missing_fields = REQUIRED_FIELDS - set(document)
        if missing_fields:
            raise ValueError(
                f"SOP document '{document_id}' is missing required fields: "
                f"{sorted(missing_fields)}"
            )

        event_type = document["event_type"]
        if event_type not in VALID_EVENT_TYPES:
            raise ValueError(
                f"SOP document '{document_id}' has invalid event_type: {event_type}"
            )

        event_types = document.get("event_types", [event_type])
        section_profiles = document.get("section_profiles", event_types)

        if not isinstance(event_types, list) or not event_types:
            raise ValueError(
                f"SOP document '{document_id}' must have a non-empty event_types list."
            )

        if not isinstance(section_profiles, list) or not section_profiles:
            raise ValueError(
                f"SOP document '{document_id}' must have a non-empty section_profiles list."
            )

        invalid_event_types = set(event_types) - VALID_EVENT_TYPES
        invalid_section_profiles = set(section_profiles) - VALID_EVENT_TYPES

        if invalid_event_types:
            raise ValueError(
                f"SOP document '{document_id}' has invalid event_types: "
                f"{sorted(invalid_event_types)}"
            )

        if invalid_section_profiles:
            raise ValueError(
                f"SOP document '{document_id}' has invalid section_profiles: "
                f"{sorted(invalid_section_profiles)}"
            )

        document["event_types"] = event_types
        document["section_profiles"] = section_profiles

    return documents


SOP_DOCUMENTS = load_sop_documents()
