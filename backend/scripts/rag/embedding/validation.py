from __future__ import annotations

from typing import Any

from scripts.rag.embedding.milvus_fields import OUTPUT_FIELDS, MilvusField


REQUIRED_EMBEDDED_FIELDS = [
    MilvusField.CHUNK_ID,
    MilvusField.CHUNK_INDEX,
    MilvusField.EMBEDDING,
    MilvusField.CONTENT,
    MilvusField.DOCUMENT_ID,
    MilvusField.DOCUMENT_TYPE,
    MilvusField.EVENT_TYPE,
    MilvusField.SECTION,
    MilvusField.SECTION_TITLE,
    MilvusField.TITLE,
    MilvusField.SOURCE_PATH,
    MilvusField.EMBEDDING_MODEL,
    MilvusField.CONTENT_HASH,
]


ARRAY_VARCHAR_FIELDS = {
    MilvusField.EVENT_TYPES,
    MilvusField.NDC,
}


def validate_positive_int(value: int, *, name: str) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer. Received: {value}")


def validate_optional_positive_int(value: int | None, *, name: str) -> None:
    if value is not None and value <= 0:
        raise ValueError(f"{name} must be a positive integer when provided. Received: {value}")


def validate_embedded_record(record: dict[str, Any], *, embedding_dim: int | None = None) -> None:
    missing = [
        field
        for field in REQUIRED_EMBEDDED_FIELDS
        if field not in record or record[field] is None or (isinstance(record[field], str) and not record[field].strip())
    ]
    if missing:
        raise ValueError(f"Embedded record missing required fields for chunk_id={record.get('chunk_id')!r}: {missing}")

    embedding = record[MilvusField.EMBEDDING]
    if not isinstance(embedding, list) or not embedding:
        raise ValueError(f"Embedding must be a non-empty list for chunk_id={record.get('chunk_id')!r}")
    if embedding_dim is not None and len(embedding) != embedding_dim:
        raise ValueError(
            f"Embedding dimension mismatch for chunk_id={record.get('chunk_id')!r}: "
            f"{len(embedding)} != {embedding_dim}"
        )

    event_types = record.get(MilvusField.EVENT_TYPES) or [record[MilvusField.EVENT_TYPE]]
    if not isinstance(event_types, list) or not event_types:
        raise ValueError(f"event_types must be a non-empty list for chunk_id={record.get('chunk_id')!r}")


def embedding_dim_from_description(description: dict[str, Any]) -> int | None:
    fields = collection_fields_from_description(description)
    for field in fields:
        if field.get("name") != MilvusField.EMBEDDING:
            continue
        params = field.get("params") or {}
        dim = params.get("dim") or field.get("dim")
        return int(dim) if dim is not None else None
    return None


def collection_fields_from_description(description: dict[str, Any]) -> list[dict[str, Any]]:
    fields = description.get("fields") or description.get("schema", {}).get("fields") or []
    return fields if isinstance(fields, list) else []


def type_name(value: Any) -> str:
    if value is None:
        return ""
    name = getattr(value, "name", None)
    if name:
        return str(name).upper()
    return str(value).rsplit(".", 1)[-1].upper()


def field_type(field: dict[str, Any]) -> str:
    return type_name(field.get("type") or field.get("data_type"))


def field_element_type(field: dict[str, Any]) -> str:
    params = field.get("params") or {}
    return type_name(field.get("element_type") or params.get("element_type"))


def validate_collection_fields(client: Any, *, collection_name: str) -> None:
    description = client.describe_collection(collection_name=collection_name)
    fields_by_name = {str(field.get("name")): field for field in collection_fields_from_description(description)}
    field_names = set(fields_by_name)
    required_fields = set(OUTPUT_FIELDS) | {MilvusField.EMBEDDING}
    missing = sorted(required_fields - field_names)
    if missing:
        raise ValueError(
            f"Existing collection schema is missing fields for {collection_name}: {missing}. "
            "Use --drop-existing or a new collection."
        )

    invalid_array_fields = []
    for name in sorted(ARRAY_VARCHAR_FIELDS):
        field = fields_by_name[name]
        if field_type(field) != "ARRAY" or field_element_type(field) != "VARCHAR":
            invalid_array_fields.append(
                f"{name} expected ARRAY[VARCHAR], got {field_type(field) or 'UNKNOWN'}"
                f"[{field_element_type(field) or 'UNKNOWN'}]"
            )
    if invalid_array_fields:
        raise ValueError(
            f"Existing collection schema has incompatible field types for {collection_name}: "
            f"{invalid_array_fields}. Use --drop-existing or a new collection."
        )


def validate_collection_dimension(client: Any, *, collection_name: str, embedding_dim: int) -> None:
    description = client.describe_collection(collection_name=collection_name)
    existing_dim = embedding_dim_from_description(description)
    if existing_dim is None:
        raise ValueError(f"Could not determine embedding dimension for existing collection: {collection_name}")
    if existing_dim != embedding_dim:
        raise ValueError(
            f"Existing collection embedding dimension mismatch for {collection_name}: "
            f"{existing_dim} != {embedding_dim}. Use --drop-existing or a new collection."
        )
