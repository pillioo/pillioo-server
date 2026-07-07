from __future__ import annotations


class MilvusField:
    CHUNK_ID = "chunk_id"
    CHUNK_INDEX = "chunk_index"
    EMBEDDING = "embedding"
    CONTENT = "content"
    DOCUMENT_ID = "document_id"
    DOCUMENT_TYPE = "document_type"
    EVENT_TYPE = "event_type"
    EVENT_TYPES = "event_types"
    SECTION = "section"
    SECTION_TITLE = "section_title"
    TITLE = "title"
    SOURCE_PATH = "source_path"
    DRUG_NAME = "drug_name"
    NORMALIZED_DRUG_NAME = "normalized_drug_name"
    RXNORM_RXCUI = "rxnorm_rxcui"
    CLASSIFICATION = "classification"
    NDC = "ndc"
    LOT = "lot"
    RECALL_NUMBER = "recall_number"
    METADATA_JSON = "metadata_json"
    EMBEDDING_MODEL = "embedding_model"
    CONTENT_HASH = "content_hash"


VARCHAR_MAX = {
    MilvusField.CHUNK_ID: 512,
    MilvusField.CONTENT: 16_384,
    MilvusField.DOCUMENT_ID: 512,
    MilvusField.DOCUMENT_TYPE: 64,
    MilvusField.EVENT_TYPE: 64,
    MilvusField.EVENT_TYPES: 64,
    MilvusField.SECTION: 128,
    MilvusField.SECTION_TITLE: 256,
    MilvusField.TITLE: 512,
    MilvusField.SOURCE_PATH: 1024,
    MilvusField.DRUG_NAME: 512,
    MilvusField.NORMALIZED_DRUG_NAME: 512,
    MilvusField.RXNORM_RXCUI: 128,
    MilvusField.CLASSIFICATION: 128,
    MilvusField.NDC: 64,
    MilvusField.LOT: 1024,
    MilvusField.RECALL_NUMBER: 128,
    MilvusField.EMBEDDING_MODEL: 128,
    MilvusField.CONTENT_HASH: 128,
}


ARRAY_MAX = {
    MilvusField.NDC: 64,
    MilvusField.EVENT_TYPES: 8,
}


OUTPUT_FIELDS = [
    MilvusField.CHUNK_ID,
    MilvusField.CHUNK_INDEX,
    MilvusField.CONTENT,
    MilvusField.DOCUMENT_ID,
    MilvusField.DOCUMENT_TYPE,
    MilvusField.EVENT_TYPE,
    MilvusField.EVENT_TYPES,
    MilvusField.SECTION,
    MilvusField.SECTION_TITLE,
    MilvusField.TITLE,
    MilvusField.SOURCE_PATH,
    MilvusField.DRUG_NAME,
    MilvusField.NORMALIZED_DRUG_NAME,
    MilvusField.RXNORM_RXCUI,
    MilvusField.CLASSIFICATION,
    MilvusField.NDC,
    MilvusField.LOT,
    MilvusField.RECALL_NUMBER,
    MilvusField.METADATA_JSON,
    MilvusField.EMBEDDING_MODEL,
    MilvusField.CONTENT_HASH,
]
