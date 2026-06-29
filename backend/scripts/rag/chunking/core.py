from __future__ import annotations

from scripts.rag.chunking.config import (
    DEFAULT_CHUNKS_PATH,
    DEFAULT_MANIFEST_PATH,
    DOCUMENTS_DIR,
    DOCUMENT_TYPE_DIRS,
    EMBEDDING_MODEL,
    MAX_MERGE_TOKENS,
    MAX_SECTION_CHARS,
    MAX_SECTION_TOKENS,
    MIN_CHUNK_TOKENS,
    OVERLAP_CHARS,
    OVERLAP_TOKENS,
    TOKEN_COUNT_METHOD,
    TOKEN_ENCODING_NAME,
)
from scripts.rag.chunking.document import (
    MarkdownSection,
    ParsedDocument,
    parse_markdown_document,
    relative_source_path,
    remove_h1,
    split_markdown_sections,
)
from scripts.rag.chunking.io import clean_outputs, write_jsonl, write_manifest
from scripts.rag.chunking.merging import merge_small_chunks, reindex_chunks
from scripts.rag.chunking.pipeline import (
    build_chunks,
    build_manifest,
    iter_document_paths,
    validate_unique_chunk_ids,
)
from scripts.rag.chunking.records import (
    build_chunk_record,
    chunk_document,
    get_chunkable_sections,
    normalize_classification,
)
from scripts.rag.chunking.splitter import (
    enforce_token_limit,
    normalize_chunk_content,
    preprocess_table_content,
    split_long_text,
    split_long_text_by_tokens,
    split_section_content,
)
from scripts.rag.chunking.tokenizer import count_tokens, estimate_token_count, get_token_encoding


__all__ = [
    "DEFAULT_CHUNKS_PATH",
    "DEFAULT_MANIFEST_PATH",
    "DOCUMENTS_DIR",
    "DOCUMENT_TYPE_DIRS",
    "EMBEDDING_MODEL",
    "MAX_MERGE_TOKENS",
    "MAX_SECTION_CHARS",
    "MAX_SECTION_TOKENS",
    "MIN_CHUNK_TOKENS",
    "OVERLAP_CHARS",
    "OVERLAP_TOKENS",
    "TOKEN_COUNT_METHOD",
    "TOKEN_ENCODING_NAME",
    "MarkdownSection",
    "ParsedDocument",
    "build_chunk_record",
    "build_chunks",
    "build_manifest",
    "chunk_document",
    "clean_outputs",
    "count_tokens",
    "enforce_token_limit",
    "estimate_token_count",
    "get_chunkable_sections",
    "get_token_encoding",
    "iter_document_paths",
    "merge_small_chunks",
    "normalize_chunk_content",
    "normalize_classification",
    "parse_markdown_document",
    "preprocess_table_content",
    "reindex_chunks",
    "relative_source_path",
    "remove_h1",
    "split_long_text",
    "split_long_text_by_tokens",
    "split_markdown_sections",
    "split_section_content",
    "validate_unique_chunk_ids",
    "write_jsonl",
    "write_manifest",
]
