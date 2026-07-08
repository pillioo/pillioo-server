from __future__ import annotations

from app.event.normalizer import sanitize_drug_name
from app.schemas.event import EventNormalized


def resolve_retrieval_drug_name(event: EventNormalized) -> str | None:
    explicit_normalized = getattr(event, "normalized_drug_name", None)
    if explicit_normalized:
        return explicit_normalized

    # Drug-name canonicalization is owned by app.event.normalizer.
    # Orchestration only adapts normalized event fields into the RAG context.
    source_name = event.product_description or event.drug_name
    normalized = sanitize_drug_name(source_name)
    return normalized or None
