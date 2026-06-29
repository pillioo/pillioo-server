from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.rag.chunking.config import (
    DOCUMENTS_DIR,
    DOCUMENT_TYPE_DIRS,
    EMBEDDING_MODEL,
    TOKEN_COUNT_METHOD,
    TOKEN_ENCODING_NAME,
)
from scripts.rag.chunking.document import parse_markdown_document
from scripts.rag.chunking.merging import merge_small_chunks, reindex_chunks
from scripts.rag.chunking.records import chunk_document


def iter_document_paths(documents_dir: Path = DOCUMENTS_DIR) -> list[Path]:
    paths: list[Path] = []
    for document_type in DOCUMENT_TYPE_DIRS:
        paths.extend(sorted((documents_dir / document_type).glob("*.md")))
    return paths


def build_chunks(documents_dir: Path = DOCUMENTS_DIR) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    warnings: list[str] = []
    document_count_by_type: Counter[str] = Counter()

    for path in iter_document_paths(documents_dir):
        document = parse_markdown_document(path)
        document_count_by_type[str(document.frontmatter["document_type"])] += 1
        document_chunks, document_warnings = chunk_document(document)
        chunks.extend(document_chunks)
        warnings.extend(document_warnings)

    chunks = merge_small_chunks(chunks)
    reindex_chunks(chunks)
    validate_unique_chunk_ids(chunks)
    manifest = build_manifest(chunks, document_count_by_type, warnings)
    return chunks, manifest


def validate_unique_chunk_ids(chunks: list[dict[str, Any]]) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for chunk in chunks:
        chunk_id = str(chunk["chunk_id"])
        if chunk_id in seen:
            duplicates.add(chunk_id)
        seen.add(chunk_id)

    if duplicates:
        raise ValueError(f"Duplicate chunk_id values: {sorted(duplicates)[:10]}")


def build_manifest(
    chunks: list[dict[str, Any]],
    document_count_by_type: Counter[str],
    warnings: list[str],
) -> dict[str, Any]:
    by_document_type: Counter[str] = Counter()
    by_event_type: Counter[str] = Counter()
    by_section: dict[str, Counter[str]] = defaultdict(Counter)
    token_counts: list[int] = []

    for chunk in chunks:
        document_type = str(chunk["document_type"])
        event_type = str(chunk["event_type"])
        section = str(chunk["section"])
        by_document_type[document_type] += 1
        by_event_type[event_type] += 1
        by_section[document_type][section] += 1
        token_counts.append(int(chunk["token_count"]))

    avg_token_count = round(sum(token_counts) / len(token_counts), 2) if token_counts else 0

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "embedding_model": EMBEDDING_MODEL,
        "token_encoding": TOKEN_ENCODING_NAME,
        "token_count_method": TOKEN_COUNT_METHOD,
        "total_documents": sum(document_count_by_type.values()),
        "total_chunks": len(chunks),
        "min_token_count": min(token_counts) if token_counts else 0,
        "max_token_count": max(token_counts) if token_counts else 0,
        "avg_token_count": avg_token_count,
        "documents_by_type": dict(sorted(document_count_by_type.items())),
        "chunks_by_document_type": dict(sorted(by_document_type.items())),
        "chunks_by_event_type": dict(sorted(by_event_type.items())),
        "chunks_by_section": {
            document_type: dict(sorted(counter.items()))
            for document_type, counter in sorted(by_section.items())
        },
        "warnings": warnings,
    }
