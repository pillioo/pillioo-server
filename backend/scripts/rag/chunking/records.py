from __future__ import annotations

import re
from typing import Any

from scripts.rag.chunking.config import (
    CONTEXT_PREFIX_RE,
    DEFAULT_MAX_SECTION_TOKENS,
    MAX_SECTION_CHARS,
    MAX_SECTION_TOKENS,
    NESTED_METADATA_FIELDS,
    SECTION_INCLUDE_BY_TYPE,
    TOP_LEVEL_METADATA_FIELDS,
)
from scripts.rag.chunking.document import (
    MarkdownSection,
    ParsedDocument,
    relative_source_path,
    remove_h1,
    split_markdown_sections,
)
from scripts.rag.chunking.schema import EvidenceChunk
from scripts.rag.chunking.splitter import split_section_content
from scripts.rag.chunking.tokenizer import count_tokens


def normalize_classification(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).lower().strip()
    normalized = normalized.replace("class ", "class_")
    normalized = re.sub(r"[^a-z0-9_]+", "_", normalized).strip("_")
    return normalized or None


def build_chunk_record(
    document: ParsedDocument,
    section: MarkdownSection,
    content: str,
    chunk_index: int,
) -> dict[str, Any]:
    frontmatter = document.frontmatter
    document_id = str(frontmatter["document_id"])
    document_type = str(frontmatter["document_type"])
    event_type = str(frontmatter["event_type"])
    event_types = frontmatter.get("event_types", [event_type])
    section_id = section.section
    chunk_id = f"{document_id}::{section_id}::{chunk_index:04d}"

    content = add_chunk_context_prefix(document=document, section=section, content=content)

    record: dict[str, Any] = {
        "chunk_id": chunk_id,
        "document_id": document_id,
        "document_type": document_type,
        "event_type": event_type,
        "event_types": event_types,
        "section": section_id,
        "section_title": section.section_title,
        "title": document.title,
        "chunk_index": chunk_index,
        "token_count": count_tokens(content),
        "content": content,
        "source_path": relative_source_path(document.path),
    }

    for field in TOP_LEVEL_METADATA_FIELDS:
        value = get_top_level_metadata_value(frontmatter, field)
        if field == "classification":
            value = normalize_classification(value)
        record[field] = value

    metadata: dict[str, Any] = {
        field: frontmatter.get(field)
        for field in NESTED_METADATA_FIELDS
        if field in frontmatter
    }
    metadata["chunk_tokens_estimate"] = record["token_count"]
    record["metadata"] = metadata

    return EvidenceChunk.model_validate(record).model_dump(mode="json")


def get_top_level_metadata_value(frontmatter: dict[str, Any], field: str) -> Any:
    if field != "ndc":
        return frontmatter.get(field)

    explicit_ndc = normalize_string_list(frontmatter.get("ndc"))
    if explicit_ndc:
        return explicit_ndc

    # Label documents expose product/package NDCs separately; duplicating a
    # representative combined list at top level makes pre-filtering simpler.
    ndc_values: list[str] = []
    for source_field in ["product_ndc", "package_ndc"]:
        for item in normalize_string_list(frontmatter.get(source_field)):
            if item not in ndc_values:
                ndc_values.append(item)

    return ndc_values or None


def normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    result: list[str] = []
    for item in values:
        if item is None:
            continue
        text = str(item).strip()
        if text and text not in result:
            result.append(text)
    return result


def add_chunk_context_prefix(document: ParsedDocument, section: MarkdownSection, content: str) -> str:
    """Add enough context for a retrieved chunk to stand alone in citations."""
    prefix = build_chunk_context_prefix(document=document, section=section)
    if content.startswith(prefix):
        return content
    return f"{prefix}\n{content}".strip()


def build_chunk_context_prefix(document: ParsedDocument, section: MarkdownSection) -> str:
    section_title = section.section_title.replace("_", " ").upper()
    return f"{section_title} - {document.title}."


def strip_chunk_context_prefix(content: str) -> str:
    lines = content.splitlines()
    if len(lines) >= 2 and CONTEXT_PREFIX_RE.fullmatch(lines[0]):
        return "\n".join(lines[1:]).strip()
    return content


def chunk_document(document: ParsedDocument) -> tuple[list[dict[str, Any]], list[str]]:
    document_type = str(document.frontmatter["document_type"])
    max_chars = MAX_SECTION_CHARS.get(document_type, 1_200)
    max_tokens = MAX_SECTION_TOKENS.get(document_type, DEFAULT_MAX_SECTION_TOKENS)
    warnings: list[str] = []
    chunks: list[dict[str, Any]] = []

    sections = get_chunkable_sections(document)
    if not sections:
        warnings.append(f"{relative_source_path(document.path)} produced 0 chunks")
        return chunks, warnings

    chunk_index = 0
    for section in sections:
        # Reserve token budget for the context prefix added to every chunk.
        prefix = build_chunk_context_prefix(document=document, section=section)
        prefix_budget = count_tokens(f"{prefix}\n")
        split_max_tokens = max(1, max_tokens - prefix_budget)
        split_max_chars = max(400, max_chars - len(prefix))
        pieces = split_section_content(
            section.content,
            max_chars=split_max_chars,
            max_tokens=split_max_tokens,
        )
        for piece in pieces:
            if not piece.strip():
                continue
            chunk = build_chunk_record(document, section, piece, chunk_index)
            if int(chunk["token_count"]) > max_tokens:
                raise ValueError(
                    f"{relative_source_path(document.path)} section {section.section} "
                    f"exceeded token limit: {chunk['token_count']} > {max_tokens}"
                )
            chunks.append(chunk)
            chunk_index += 1

    if not chunks:
        warnings.append(f"{relative_source_path(document.path)} produced 0 chunks")

    return chunks, warnings


def get_chunkable_sections(document: ParsedDocument) -> list[MarkdownSection]:
    document_type = str(document.frontmatter["document_type"])
    if document_type == "recall_notice":
        content = remove_h1(document.body)
        return (
            [MarkdownSection(section=document_type, section_title=document.title, content=content)]
            if content
            else []
        )

    sections = split_markdown_sections(document.body)
    included_sections = SECTION_INCLUDE_BY_TYPE.get(document_type)
    if not included_sections:
        return sections

    return [section for section in sections if section.section in included_sections]
