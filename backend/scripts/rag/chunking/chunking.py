from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from scripts.rag.chunking.schema import EvidenceChunk
from scripts.rag.common import slugify

try:
    import tiktoken
except ImportError:  # pragma: no cover - exercised only when optional dependency is missing.
    tiktoken = None


ROOT_DIR = Path(__file__).resolve().parents[2]
RAG_DIR = ROOT_DIR / "data" / "rag"
DOCUMENTS_DIR = RAG_DIR / "documents"
PROCESSED_DIR = RAG_DIR / "processed"
DEFAULT_CHUNKS_PATH = PROCESSED_DIR / "evidence_chunks.jsonl"
DEFAULT_MANIFEST_PATH = PROCESSED_DIR / "chunk_manifest.json"
load_dotenv(ROOT_DIR / ".env")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
TOKEN_ENCODING_NAME = "cl100k_base"
TOKEN_COUNT_METHOD = "tiktoken" if tiktoken is not None else "char_estimate"

VALID_DOCUMENT_TYPES = {"label", "recall_notice", "sop", "policy", "shortage_notice"}
VALID_EVENT_TYPES = {"recall", "shortage", "label_update"}
DOCUMENT_TYPE_DIRS = ["label", "recall_notice", "sop", "policy"]

MAX_SECTION_TOKENS = {
    "label": 512,
    "recall_notice": 512,
    "sop": 384,
    "policy": 384,
    "shortage_notice": 512,
}
DEFAULT_MAX_SECTION_TOKENS = 512
OVERLAP_TOKENS = 64

SECTION_INCLUDE_BY_TYPE = {
    "label": {
        "indications_and_usage",
        "boxed_warning",
        "warnings",
        "contraindications",
        "dosage_and_administration",
        "adverse_reactions",
        "drug_interactions",
        "use_in_specific_populations",
        "how_supplied",
        "storage_and_handling",
    },
    "sop": {
        "required_inputs",
        "evidence_requirements",
        "procedure",
        "safety_controls",
        "exception_handling",
        "review_routing",
        "audit_requirements",
        "completion_criteria",
    },
    "policy": {
        "policy_statement",
        "evidence_requirements",
        "required_actions",
        "escalation_criteria",
        "review_routing_rules",
        "approval_requirements",
        "prohibited_actions",
        "audit_requirements",
        "completion_criteria",
    },
}

TOP_LEVEL_METADATA_FIELDS = [
    "drug_name",
    "normalized_drug_name",
    "rxnorm_rxcui",
    "classification",
]

NESTED_METADATA_FIELDS = [
    "ndc",
    "lot",
    "lot_scope",
    "recall_number",
    "priority",
    "requires_human_approval",
    "source",
    "source_record_id",
    "rxnorm_name",
    "rxnorm_tty",
    "drug_identity_match_basis",
    "openfda_drug_name",
    "product_ndc",
    "package_ndc",
    "route",
    "policy_id",
    "sop_id",
]


@dataclass(frozen=True)
class ParsedDocument:
    path: Path
    frontmatter: dict[str, Any]
    title: str
    body: str


@dataclass(frozen=True)
class MarkdownSection:
    section: str
    section_title: str
    content: str


def parse_markdown_document(path: Path) -> ParsedDocument:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"Markdown document is missing frontmatter: {path}")

    try:
        _empty, frontmatter_text, body = text.split("---\n", 2)
    except ValueError as exc:
        raise ValueError(f"Markdown document has malformed frontmatter: {path}") from exc

    frontmatter = yaml.safe_load(frontmatter_text)
    if not isinstance(frontmatter, dict):
        raise ValueError(f"Markdown frontmatter must be an object: {path}")

    validate_frontmatter(frontmatter, path)
    title = str(frontmatter.get("title") or extract_h1_title(body) or frontmatter["document_id"])
    return ParsedDocument(path=path, frontmatter=frontmatter, title=title, body=body.strip())


def validate_frontmatter(frontmatter: dict[str, Any], path: Path) -> None:
    for field in ["document_id", "document_type", "event_type"]:
        if not frontmatter.get(field):
            raise ValueError(f"Markdown frontmatter is missing {field}: {path}")

    document_type = str(frontmatter["document_type"])
    event_type = str(frontmatter["event_type"])
    if document_type not in VALID_DOCUMENT_TYPES:
        raise ValueError(f"Invalid document_type {document_type!r}: {path}")
    if event_type not in VALID_EVENT_TYPES:
        raise ValueError(f"Invalid event_type {event_type!r}: {path}")

    event_types = frontmatter.get("event_types", [event_type])
    if not isinstance(event_types, list) or not event_types:
        raise ValueError(f"event_types must be a non-empty list: {path}")

    invalid_event_types = set(str(item) for item in event_types) - VALID_EVENT_TYPES
    if invalid_event_types:
        raise ValueError(f"Invalid event_types {sorted(invalid_event_types)}: {path}")


def extract_h1_title(body: str) -> str:
    match = re.search(r"^#\s+(.+?)\s*$", body, flags=re.MULTILINE)
    return match.group(1).strip() if match else ""


def split_markdown_sections(body: str) -> list[MarkdownSection]:
    matches = list(re.finditer(r"^##\s+(.+?)\s*$", body, flags=re.MULTILINE))
    if not matches:
        content = remove_h1(body).strip()
        return [MarkdownSection(section="document", section_title="Document", content=content)] if content else []

    sections: list[MarkdownSection] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        section_title = match.group(1).strip()
        content = body[start:end].strip()
        if content:
            sections.append(
                MarkdownSection(
                    section=slugify(section_title, separator="_"),
                    section_title=section_title,
                    content=content,
                )
            )

    return sections


def remove_h1(body: str) -> str:
    return re.sub(r"^#\s+.+?\s*$", "", body, count=1, flags=re.MULTILINE).strip()


def split_section_content(content: str, max_tokens: int, overlap_tokens: int = OVERLAP_TOKENS) -> list[str]:
    content = normalize_chunk_content(content)
    if count_tokens(content) <= max_tokens:
        return [content] if content else []

    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", content) if paragraph.strip()]
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        if count_tokens(paragraph) > max_tokens:
            if current:
                chunks.append(current.strip())
                current = ""
            chunks.extend(split_long_text(paragraph, max_tokens=max_tokens, overlap_tokens=overlap_tokens))
            continue

        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if count_tokens(candidate) <= max_tokens:
            current = candidate
            continue

        if current:
            chunks.append(current.strip())
        current = prepend_token_overlap(previous=current, content=paragraph, overlap_tokens=overlap_tokens, max_tokens=max_tokens)

    if current:
        chunks.append(current.strip())

    return chunks


def prepend_token_overlap(previous: str, content: str, overlap_tokens: int, max_tokens: int) -> str:
    overlap = get_token_tail(previous, overlap_tokens)
    if not overlap:
        return content

    candidate = f"{overlap}\n\n{content}".strip()
    return candidate if count_tokens(candidate) <= max_tokens else content


def get_token_tail(content: str, token_count: int) -> str:
    encoding = get_token_encoding()
    if encoding is None:
        return content[-token_count * 4 :].strip()

    token_ids = encoding.encode(content)
    if not token_ids:
        return ""
    return encoding.decode(token_ids[-token_count:]).strip()


def split_long_text(text: str, max_tokens: int, overlap_tokens: int) -> list[str]:
    encoding = get_token_encoding()
    if encoding is None:
        return split_long_text_by_estimated_tokens(text, max_tokens=max_tokens, overlap_tokens=overlap_tokens)

    token_ids = encoding.encode(text)
    if len(token_ids) <= max_tokens:
        return [text.strip()] if text.strip() else []

    chunks: list[str] = []
    start = 0
    while start < len(token_ids):
        end = min(start + max_tokens, len(token_ids))
        chunk = encoding.decode(token_ids[start:end]).strip()
        while count_tokens(chunk) > max_tokens and end > start + 1:
            end -= 1
            chunk = encoding.decode(token_ids[start:end]).strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(token_ids):
            break
        start = max(end - overlap_tokens, start + 1)
    return chunks


def split_long_text_by_estimated_tokens(text: str, max_tokens: int, overlap_tokens: int) -> list[str]:
    max_chars = max_tokens * 4
    overlap_chars = overlap_tokens * 4
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            boundary = max(text.rfind(". ", start, end), text.rfind("; ", start, end))
            if boundary > start + max_chars // 2:
                end = boundary + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap_chars, start + 1)
    return chunks


def normalize_chunk_content(content: str) -> str:
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    content = re.sub(r"[ \t]+", " ", content)
    content = re.sub(r"\n{3,}", "\n\n", content)
    return content.strip()


@lru_cache(maxsize=1)
def get_token_encoding() -> Any:
    if tiktoken is None:
        return None
    try:
        return tiktoken.encoding_for_model(EMBEDDING_MODEL)
    except KeyError:
        return tiktoken.get_encoding(TOKEN_ENCODING_NAME)


def count_tokens(content: str) -> int:
    encoding = get_token_encoding()
    if encoding is None:
        return estimate_token_count(content)
    return max(1, len(encoding.encode(content)))


def estimate_token_count(content: str) -> int:
    return max(1, round(len(content) / 4))


def normalize_classification(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).lower().strip()
    normalized = normalized.replace("class ", "class_")
    normalized = re.sub(r"[^a-z0-9_]+", "_", normalized).strip("_")
    return normalized or None


def relative_source_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT_DIR).as_posix()
    except ValueError:
        return path.as_posix()


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
        value = frontmatter.get(field)
        if field == "classification":
            value = normalize_classification(value)
        record[field] = value

    metadata = {
        field: frontmatter.get(field)
        for field in NESTED_METADATA_FIELDS
        if field in frontmatter
    }
    metadata["chunk_tokens_estimate"] = record["token_count"]
    record["metadata"] = metadata

    return EvidenceChunk.model_validate(record).model_dump(mode="json")


def chunk_document(document: ParsedDocument) -> tuple[list[dict[str, Any]], list[str]]:
    document_type = str(document.frontmatter["document_type"])
    max_tokens = MAX_SECTION_TOKENS.get(document_type, DEFAULT_MAX_SECTION_TOKENS)
    warnings: list[str] = []
    chunks: list[dict[str, Any]] = []

    sections = get_chunkable_sections(document)
    if not sections:
        warnings.append(f"{relative_source_path(document.path)} produced 0 chunks")
        return chunks, warnings

    chunk_index = 0
    for section in sections:
        pieces = split_section_content(section.content, max_tokens=max_tokens)
        for piece in pieces:
            if not piece.strip():
                continue
            if count_tokens(piece) > max_tokens * 1.25:
                warnings.append(
                    f"{relative_source_path(document.path)} section {section.section} "
                    f"has chunk over target size"
                )
            chunks.append(build_chunk_record(document, section, piece, chunk_index))
            chunk_index += 1

    if not chunks:
        warnings.append(f"{relative_source_path(document.path)} produced 0 chunks")

    return chunks, warnings


def get_chunkable_sections(document: ParsedDocument) -> list[MarkdownSection]:
    document_type = str(document.frontmatter["document_type"])
    if document_type in {"recall_notice", "shortage_notice"}:
        content = remove_h1(document.body)
        return [
            MarkdownSection(
                section=document_type,
                section_title=document.title,
                content=content,
            )
        ] if content else []

    sections = split_markdown_sections(document.body)
    included_sections = SECTION_INCLUDE_BY_TYPE.get(document_type)
    if not included_sections:
        return sections

    return [section for section in sections if section.section in included_sections]


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


def write_jsonl(records: list[dict[str, Any]], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def write_manifest(manifest: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def clean_outputs(*paths: Path) -> None:
    for path in paths:
        if path.exists():
            path.unlink()
