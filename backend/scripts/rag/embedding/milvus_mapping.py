from __future__ import annotations

from typing import Any

from scripts.rag.embedding.milvus_fields import ARRAY_MAX, VARCHAR_MAX, MilvusField
from scripts.rag.embedding.validation import validate_embedded_record


def truncate(
    value: Any,
    max_length: int,
    *,
    field: str,
    chunk_id: str,
    strict: bool = False,
) -> str:
    if value is None:
        return ""
    text = str(value)
    if len(text) > max_length:
        message = f"[MILVUS] field={field} chunk_id={chunk_id} truncated {len(text)} -> {max_length} chars"
        if strict:
            raise ValueError(message)
        print(message, flush=True)
    return text[:max_length]


def as_array(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def as_varchar_array(value: Any, *, field: str, chunk_id: str, max_length: int, max_capacity: int) -> list[str]:
    values = as_array(value)
    if len(values) > max_capacity:
        print(
            f"[MILVUS] field={field} chunk_id={chunk_id} truncated array {len(values)} -> {max_capacity} items",
            flush=True,
        )
    return [
        truncate(item, max_length, field=field, chunk_id=chunk_id)
        for item in values[:max_capacity]
        if item is not None and str(item).strip()
    ]


def to_milvus_row(record: dict[str, Any], *, embedding_dim: int | None = None) -> dict[str, Any]:
    validate_embedded_record(record, embedding_dim=embedding_dim)
    # Never truncate the primary key; collisions here would silently overwrite evidence rows.
    chunk_id = truncate(
        record[MilvusField.CHUNK_ID],
        VARCHAR_MAX[MilvusField.CHUNK_ID],
        field=MilvusField.CHUNK_ID,
        chunk_id=str(record[MilvusField.CHUNK_ID]),
        strict=True,
    )
    return {
        MilvusField.CHUNK_ID: chunk_id,
        MilvusField.CHUNK_INDEX: int(record[MilvusField.CHUNK_INDEX]),
        MilvusField.EMBEDDING: record[MilvusField.EMBEDDING],
        MilvusField.CONTENT: truncate(record[MilvusField.CONTENT], VARCHAR_MAX[MilvusField.CONTENT], field=MilvusField.CONTENT, chunk_id=chunk_id),
        MilvusField.DOCUMENT_ID: truncate(record[MilvusField.DOCUMENT_ID], VARCHAR_MAX[MilvusField.DOCUMENT_ID], field=MilvusField.DOCUMENT_ID, chunk_id=chunk_id),
        MilvusField.DOCUMENT_TYPE: truncate(record[MilvusField.DOCUMENT_TYPE], VARCHAR_MAX[MilvusField.DOCUMENT_TYPE], field=MilvusField.DOCUMENT_TYPE, chunk_id=chunk_id),
        MilvusField.EVENT_TYPE: truncate(record[MilvusField.EVENT_TYPE], VARCHAR_MAX[MilvusField.EVENT_TYPE], field=MilvusField.EVENT_TYPE, chunk_id=chunk_id),
        MilvusField.EVENT_TYPES: as_varchar_array(
            record.get(MilvusField.EVENT_TYPES) or [record[MilvusField.EVENT_TYPE]],
            field=MilvusField.EVENT_TYPES,
            chunk_id=chunk_id,
            max_length=VARCHAR_MAX[MilvusField.EVENT_TYPES],
            max_capacity=ARRAY_MAX[MilvusField.EVENT_TYPES],
        ),
        MilvusField.SECTION: truncate(record[MilvusField.SECTION], VARCHAR_MAX[MilvusField.SECTION], field=MilvusField.SECTION, chunk_id=chunk_id),
        MilvusField.SECTION_TITLE: truncate(record[MilvusField.SECTION_TITLE], VARCHAR_MAX[MilvusField.SECTION_TITLE], field=MilvusField.SECTION_TITLE, chunk_id=chunk_id),
        MilvusField.TITLE: truncate(record[MilvusField.TITLE], VARCHAR_MAX[MilvusField.TITLE], field=MilvusField.TITLE, chunk_id=chunk_id),
        MilvusField.SOURCE_PATH: truncate(record[MilvusField.SOURCE_PATH], VARCHAR_MAX[MilvusField.SOURCE_PATH], field=MilvusField.SOURCE_PATH, chunk_id=chunk_id),
        MilvusField.DRUG_NAME: truncate(record.get(MilvusField.DRUG_NAME), VARCHAR_MAX[MilvusField.DRUG_NAME], field=MilvusField.DRUG_NAME, chunk_id=chunk_id),
        MilvusField.NORMALIZED_DRUG_NAME: truncate(
            record.get(MilvusField.NORMALIZED_DRUG_NAME),
            VARCHAR_MAX[MilvusField.NORMALIZED_DRUG_NAME],
            field=MilvusField.NORMALIZED_DRUG_NAME,
            chunk_id=chunk_id,
        ),
        MilvusField.RXNORM_RXCUI: truncate(record.get(MilvusField.RXNORM_RXCUI), VARCHAR_MAX[MilvusField.RXNORM_RXCUI], field=MilvusField.RXNORM_RXCUI, chunk_id=chunk_id),
        MilvusField.CLASSIFICATION: truncate(record.get(MilvusField.CLASSIFICATION), VARCHAR_MAX[MilvusField.CLASSIFICATION], field=MilvusField.CLASSIFICATION, chunk_id=chunk_id),
        MilvusField.NDC: as_varchar_array(
            record.get(MilvusField.NDC),
            field=MilvusField.NDC,
            chunk_id=chunk_id,
            max_length=VARCHAR_MAX[MilvusField.NDC],
            max_capacity=ARRAY_MAX[MilvusField.NDC],
        ),
        MilvusField.LOT: truncate(record.get(MilvusField.LOT), VARCHAR_MAX[MilvusField.LOT], field=MilvusField.LOT, chunk_id=chunk_id),
        MilvusField.RECALL_NUMBER: truncate(record.get(MilvusField.RECALL_NUMBER), VARCHAR_MAX[MilvusField.RECALL_NUMBER], field=MilvusField.RECALL_NUMBER, chunk_id=chunk_id),
        MilvusField.METADATA_JSON: record.get("metadata", {}),
        MilvusField.EMBEDDING_MODEL: truncate(record[MilvusField.EMBEDDING_MODEL], VARCHAR_MAX[MilvusField.EMBEDDING_MODEL], field=MilvusField.EMBEDDING_MODEL, chunk_id=chunk_id),
        MilvusField.CONTENT_HASH: truncate(record[MilvusField.CONTENT_HASH], VARCHAR_MAX[MilvusField.CONTENT_HASH], field=MilvusField.CONTENT_HASH, chunk_id=chunk_id),
    }
