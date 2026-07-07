from __future__ import annotations

from scripts.rag.embedding.milvus_fields import ARRAY_MAX, VARCHAR_MAX, MilvusField


def create_evidence_schema(client, *, embedding_dim: int):
    from pymilvus import DataType, MilvusClient

    schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
    schema.add_field(MilvusField.CHUNK_ID, DataType.VARCHAR, is_primary=True, max_length=VARCHAR_MAX[MilvusField.CHUNK_ID])
    schema.add_field(MilvusField.CHUNK_INDEX, DataType.INT64)
    schema.add_field(MilvusField.EMBEDDING, DataType.FLOAT_VECTOR, dim=embedding_dim)
    schema.add_field(MilvusField.CONTENT, DataType.VARCHAR, max_length=VARCHAR_MAX[MilvusField.CONTENT])
    schema.add_field(MilvusField.DOCUMENT_ID, DataType.VARCHAR, max_length=VARCHAR_MAX[MilvusField.DOCUMENT_ID])
    schema.add_field(MilvusField.DOCUMENT_TYPE, DataType.VARCHAR, max_length=VARCHAR_MAX[MilvusField.DOCUMENT_TYPE])
    schema.add_field(MilvusField.EVENT_TYPE, DataType.VARCHAR, max_length=VARCHAR_MAX[MilvusField.EVENT_TYPE])
    schema.add_field(
        MilvusField.EVENT_TYPES,
        DataType.ARRAY,
        element_type=DataType.VARCHAR,
        max_capacity=ARRAY_MAX[MilvusField.EVENT_TYPES],
        max_length=VARCHAR_MAX[MilvusField.EVENT_TYPES],
    )
    schema.add_field(MilvusField.SECTION, DataType.VARCHAR, max_length=VARCHAR_MAX[MilvusField.SECTION])
    schema.add_field(MilvusField.SECTION_TITLE, DataType.VARCHAR, max_length=VARCHAR_MAX[MilvusField.SECTION_TITLE])
    schema.add_field(MilvusField.TITLE, DataType.VARCHAR, max_length=VARCHAR_MAX[MilvusField.TITLE])
    schema.add_field(MilvusField.SOURCE_PATH, DataType.VARCHAR, max_length=VARCHAR_MAX[MilvusField.SOURCE_PATH])
    schema.add_field(MilvusField.DRUG_NAME, DataType.VARCHAR, max_length=VARCHAR_MAX[MilvusField.DRUG_NAME])
    schema.add_field(MilvusField.NORMALIZED_DRUG_NAME, DataType.VARCHAR, max_length=VARCHAR_MAX[MilvusField.NORMALIZED_DRUG_NAME])
    schema.add_field(MilvusField.RXNORM_RXCUI, DataType.VARCHAR, max_length=VARCHAR_MAX[MilvusField.RXNORM_RXCUI])
    schema.add_field(MilvusField.CLASSIFICATION, DataType.VARCHAR, max_length=VARCHAR_MAX[MilvusField.CLASSIFICATION])
    # Keep NDC filterable for retrieval; JSON fields are harder to use in Milvus filter expressions.
    schema.add_field(
        MilvusField.NDC,
        DataType.ARRAY,
        element_type=DataType.VARCHAR,
        max_capacity=ARRAY_MAX[MilvusField.NDC],
        max_length=VARCHAR_MAX[MilvusField.NDC],
    )
    schema.add_field(MilvusField.LOT, DataType.VARCHAR, max_length=VARCHAR_MAX[MilvusField.LOT])
    schema.add_field(MilvusField.RECALL_NUMBER, DataType.VARCHAR, max_length=VARCHAR_MAX[MilvusField.RECALL_NUMBER])
    schema.add_field(MilvusField.METADATA_JSON, DataType.JSON)
    schema.add_field(MilvusField.EMBEDDING_MODEL, DataType.VARCHAR, max_length=VARCHAR_MAX[MilvusField.EMBEDDING_MODEL])
    schema.add_field(MilvusField.CONTENT_HASH, DataType.VARCHAR, max_length=VARCHAR_MAX[MilvusField.CONTENT_HASH])
    return schema


def create_index_params(client):
    index_params = client.prepare_index_params()
    index_params.add_index(
        field_name=MilvusField.EMBEDDING,
        index_type="IVF_FLAT",
        metric_type="COSINE",
        params={"nlist": 128},
    )
    return index_params
