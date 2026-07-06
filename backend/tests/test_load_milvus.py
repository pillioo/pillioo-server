from __future__ import annotations

import pytest

from scripts.rag.embedding.milvus_mapping import to_milvus_row, truncate
from scripts.rag.embedding.milvus_fields import OUTPUT_FIELDS, MilvusField
from scripts.rag.embedding.validation import validate_collection_dimension, validate_collection_fields


def make_embedded_record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "chunk_id": "chunk-1",
        "embedding": [0.1, 0.2],
        "content": "body",
        "document_id": "doc-1",
        "document_type": "label",
        "event_type": "label_update",
        "event_types": ["label_update"],
        "section": "warnings",
        "section_title": "warnings",
        "title": "Label",
        "source_path": "data/rag/documents/label/doc.md",
        "drug_name": "drug",
        "normalized_drug_name": "drug",
        "rxnorm_rxcui": "123",
        "classification": None,
        "ndc": ["12345-6789-01"],
        "lot": None,
        "recall_number": None,
        "metadata": {},
        "embedding_model": "text-embedding-3-small",
        "content_hash": "hash",
    }
    record.update(overrides)
    return record


def test_to_milvus_row_uses_filterable_ndc_array() -> None:
    row = to_milvus_row(make_embedded_record(ndc="12345-6789-01"))

    assert row["ndc"] == ["12345-6789-01"]
    assert "ndc_json" not in row


def test_to_milvus_row_uses_filterable_event_types_array() -> None:
    row = to_milvus_row(make_embedded_record(event_types=["recall", "shortage"]))

    assert row["event_types"] == ["recall", "shortage"]
    assert "event_types_json" not in row


def test_to_milvus_row_validates_required_fields() -> None:
    record = make_embedded_record(content="")

    with pytest.raises(ValueError, match="missing required fields"):
        to_milvus_row(record)


def test_to_milvus_row_validates_embedding_dimension() -> None:
    record = make_embedded_record(embedding=[0.1, 0.2])

    with pytest.raises(ValueError, match="Embedding dimension mismatch"):
        to_milvus_row(record, embedding_dim=3)


def test_to_milvus_row_rejects_truncated_primary_key() -> None:
    record = make_embedded_record(chunk_id="x" * 513)

    with pytest.raises(ValueError, match="field=chunk_id"):
        to_milvus_row(record)


def test_truncate_logs_non_strict_truncation(capsys: pytest.CaptureFixture[str]) -> None:
    value = truncate("abcdef", 3, field="content", chunk_id="chunk-1")

    assert value == "abc"
    assert "field=content chunk_id=chunk-1 truncated 6 -> 3 chars" in capsys.readouterr().out


class FakeMilvusClient:
    def __init__(self, dim: int | None, fields: list[dict[str, object]] | None = None) -> None:
        self.dim = dim
        self.fields = fields

    def describe_collection(self, *, collection_name: str) -> dict[str, object]:
        field: dict[str, object] = {"name": "embedding"}
        if self.dim is not None:
            field["params"] = {"dim": self.dim}
        fields = [field]
        if self.fields is not None:
            fields = self.fields
        return {"fields": fields}


def make_collection_fields(
    *,
    event_types_type: str = "ARRAY",
    event_types_element_type: str = "VARCHAR",
    ndc_type: str = "ARRAY",
    ndc_element_type: str = "VARCHAR",
) -> list[dict[str, object]]:
    fields = []
    for name in [MilvusField.EMBEDDING, *OUTPUT_FIELDS]:
        field: dict[str, object] = {"name": name, "type": "VARCHAR"}
        if name == MilvusField.EMBEDDING:
            field = {"name": name, "type": "FLOAT_VECTOR"}
        elif name == MilvusField.EVENT_TYPES:
            field = {"name": name, "type": event_types_type, "element_type": event_types_element_type}
        elif name == MilvusField.NDC:
            field = {"name": name, "type": ndc_type, "element_type": ndc_element_type}
        fields.append(field)
    return fields


def test_validate_collection_dimension_accepts_matching_dimension() -> None:
    validate_collection_dimension(FakeMilvusClient(1536), collection_name="evidence_chunks", embedding_dim=1536)


def test_validate_collection_dimension_rejects_mismatch() -> None:
    with pytest.raises(ValueError, match="embedding dimension mismatch"):
        validate_collection_dimension(FakeMilvusClient(384), collection_name="evidence_chunks", embedding_dim=1536)


def test_validate_collection_fields_accepts_expected_schema() -> None:
    validate_collection_fields(FakeMilvusClient(None, make_collection_fields()), collection_name="evidence_chunks")


def test_validate_collection_fields_rejects_old_event_types_schema() -> None:
    fields = make_collection_fields()
    fields = [field for field in fields if field["name"] != MilvusField.EVENT_TYPES]
    fields.append({"name": "event_types_json", "type": "JSON"})

    with pytest.raises(ValueError, match="missing fields"):
        validate_collection_fields(FakeMilvusClient(None, fields), collection_name="evidence_chunks")


def test_validate_collection_fields_rejects_scalar_event_types_field() -> None:
    fields = make_collection_fields(event_types_type="VARCHAR", event_types_element_type="")

    with pytest.raises(ValueError, match="expected ARRAY\\[VARCHAR\\]"):
        validate_collection_fields(FakeMilvusClient(None, fields), collection_name="evidence_chunks")


def test_validate_collection_fields_rejects_array_with_wrong_element_type() -> None:
    fields = make_collection_fields(ndc_type="ARRAY", ndc_element_type="INT64")

    with pytest.raises(ValueError, match="expected ARRAY\\[VARCHAR\\]"):
        validate_collection_fields(FakeMilvusClient(None, fields), collection_name="evidence_chunks")
