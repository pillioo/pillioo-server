from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from scripts.rag.chunking.config import ROOT_DIR, VALID_DOCUMENT_TYPES, VALID_EVENT_TYPES
from scripts.rag.common import slugify


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
    text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    if not text.startswith("---\n"):
        raise ValueError(f"Markdown document is missing frontmatter: {path}")

    match = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, flags=re.DOTALL)
    if not match:
        raise ValueError(f"Markdown document has malformed frontmatter: {path}")

    frontmatter_text, body = match.groups()

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
    preamble = remove_h1(body[: matches[0].start()]).strip()
    if preamble:
        sections.append(
            MarkdownSection(
                section="overview",
                section_title="Overview",
                content=preamble,
            )
        )

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


def relative_source_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT_DIR).as_posix()
    except ValueError:
        return path.as_posix()
