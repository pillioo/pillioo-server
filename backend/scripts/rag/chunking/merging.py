from __future__ import annotations

from typing import Any

from scripts.rag.chunking.config import (
    DEFAULT_MAX_SECTION_TOKENS,
    MAX_MERGE_TOKENS,
    MAX_SECTION_TOKENS,
    MIN_CHUNK_TOKENS,
)
from scripts.rag.chunking.records import strip_chunk_context_prefix
from scripts.rag.chunking.tokenizer import count_tokens


def merge_small_chunks(
    chunks: list[dict[str, Any]],
    min_tokens: int = MIN_CHUNK_TOKENS,
    max_tokens: int = MAX_MERGE_TOKENS,
) -> list[dict[str, Any]]:
    """Merge tiny neighboring chunks without crossing document/section bounds."""
    result = list(chunks)
    i = 0
    while i < len(result):
        chunk = result[i]
        if chunk["token_count"] >= min_tokens:
            i += 1
            continue

        merged = False

        if i + 1 < len(result):
            nxt = result[i + 1]
            merge_limit = get_merge_token_limit(chunk, nxt, default=max_tokens)
            merged_content = chunk["content"] + "\n\n" + strip_chunk_context_prefix(nxt["content"])
            merged_tokens = count_tokens(merged_content)
            if (
                nxt["document_id"] == chunk["document_id"]
                and nxt["section"] == chunk["section"]
                and merged_tokens <= merge_limit
            ):
                nxt["content"] = merged_content
                nxt["token_count"] = merged_tokens
                nxt["metadata"]["chunk_tokens_estimate"] = merged_tokens
                result.pop(i)
                merged = True

        if not merged and i > 0:
            prev = result[i - 1]
            merge_limit = get_merge_token_limit(prev, chunk, default=max_tokens)
            merged_content = prev["content"] + "\n\n" + strip_chunk_context_prefix(chunk["content"])
            merged_tokens = count_tokens(merged_content)
            if (
                prev["document_id"] == chunk["document_id"]
                and prev["section"] == chunk["section"]
                and merged_tokens <= merge_limit
            ):
                prev["content"] = merged_content
                prev["token_count"] = merged_tokens
                prev["metadata"]["chunk_tokens_estimate"] = merged_tokens
                result.pop(i)
                merged = True

        if not merged:
            i += 1

    return result


def get_merge_token_limit(left: dict[str, Any], right: dict[str, Any], default: int) -> int:
    """Respect stricter per-document token limits during post-split merging."""
    document_type = str(left.get("document_type") or right.get("document_type") or "")
    return min(default, MAX_SECTION_TOKENS.get(document_type, DEFAULT_MAX_SECTION_TOKENS))


def reindex_chunks(chunks: list[dict[str, Any]]) -> None:
    doc_counters: dict[str, int] = {}
    for chunk in chunks:
        doc_id = str(chunk["document_id"])
        idx = doc_counters.get(doc_id, 0)
        chunk["chunk_index"] = idx
        chunk["chunk_id"] = f"{doc_id}::{chunk['section']}::{idx:04d}"
        doc_counters[doc_id] = idx + 1
