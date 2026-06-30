from __future__ import annotations

import re
from typing import Any

from scripts.rag.chunking.config import (
    DEFAULT_MAX_SECTION_TOKENS,
    OVERLAP_CHARS,
    OVERLAP_TOKENS,
)
from scripts.rag.chunking.tokenizer import count_tokens, get_token_encoding


_TABLE_MARKER_RE = re.compile(r"(?=\bTable\s+\d+\b)", re.IGNORECASE)
_CONCENTRATION_AFTER_NUMBER_RE = re.compile(r"(\b\d+(?:\.\d+)?)\s+(\d{3,5}\s+mcg/mL\b)")
_TABLE_ROW_END_RE = re.compile(r"(\b\d{2,3}(?:\.\d+)?)\s+([A-Z][a-z]{5,})")


def preprocess_table_content(content: str) -> str:
    """Recover paragraph breaks in dense openFDA table text before splitting."""
    content = _TABLE_MARKER_RE.sub("\n\n", content)
    content = _CONCENTRATION_AFTER_NUMBER_RE.sub(r"\1\n\n\2", content)
    content = _TABLE_ROW_END_RE.sub(r"\1\n\n\2", content)
    content = re.sub(r"\n{3,}", "\n\n", content)
    return content


def split_section_content(
    content: str,
    max_chars: int,
    overlap_chars: int = OVERLAP_CHARS,
    max_tokens: int = DEFAULT_MAX_SECTION_TOKENS,
) -> list[str]:
    content = normalize_chunk_content(content)
    content = preprocess_table_content(content)
    if len(content) <= max_chars and count_tokens(content) <= max_tokens:
        return [content] if content else []

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]
    if len(paragraphs) == 1:
        para = paragraphs[0]
        if len(para) > max_chars or count_tokens(para) > max_tokens:
            effective = token_aware_max_chars(para, max_chars, max_tokens)
            return enforce_token_limit(
                split_long_text(para, max_chars=effective, overlap_chars=overlap_chars),
                max_tokens=max_tokens,
                overlap_tokens=OVERLAP_TOKENS,
            )

    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        para_tokens = count_tokens(paragraph)
        if len(paragraph) > max_chars or para_tokens > max_tokens:
            if current:
                chunks.append(current.strip())
                current = ""
            effective = token_aware_max_chars(paragraph, max_chars, max_tokens)
            chunks.extend(split_long_text(paragraph, max_chars=effective, overlap_chars=overlap_chars))
            continue

        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= max_chars and count_tokens(candidate) <= max_tokens:
            current = candidate
            continue

        if current:
            chunks.append(current.strip())
        current = paragraph

    if current:
        chunks.append(current.strip())

    return enforce_token_limit(chunks, max_tokens=max_tokens, overlap_tokens=OVERLAP_TOKENS)


def token_aware_max_chars(text: str, max_chars: int, max_tokens: int) -> int:
    """Shrink char windows for numeric/NDC-heavy text where tokens are denser."""
    tokens = count_tokens(text)
    if tokens == 0:
        return max_chars
    chars_per_token = len(text) / tokens
    adjusted = int(max_tokens * chars_per_token * 0.9)
    return max(200, min(max_chars, adjusted))


def enforce_token_limit(chunks: list[str], max_tokens: int, overlap_tokens: int) -> list[str]:
    """Apply the token ceiling after all paragraph and sentence heuristics."""
    limited_chunks: list[str] = []
    for chunk in chunks:
        if count_tokens(chunk) <= max_tokens:
            limited_chunks.append(chunk)
            continue
        limited_chunks.extend(split_long_text_by_tokens(chunk, max_tokens=max_tokens, overlap_tokens=overlap_tokens))
    return limited_chunks


def split_long_text_by_tokens(text: str, max_tokens: int, overlap_tokens: int) -> list[str]:
    encoding = get_token_encoding()
    if encoding is None:
        max_chars = max_tokens * 4
        overlap_chars = overlap_tokens * 4
        return split_long_text(text, max_chars=max_chars, overlap_chars=overlap_chars)

    token_ids = encoding.encode(text)
    chunks: list[str] = []
    start = 0
    while start < len(token_ids):
        end = min(start + max_tokens, len(token_ids))
        if end < len(token_ids):
            end = find_token_sentence_end(encoding, token_ids, start, end)
        chunk = encoding.decode(token_ids[start:end]).strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(token_ids):
            break
        start = max(end - overlap_tokens, start + 1)
        start = find_token_sentence_start(encoding, token_ids, start, end)
    return chunks


def find_token_sentence_end(encoding: Any, token_ids: list[int], start: int, end: int) -> int:
    min_end = start + max(1, (end - start) // 2)
    for candidate in range(end, min_end, -1):
        text = encoding.decode(token_ids[start:candidate]).rstrip()
        if text.endswith((".", ";", ":")):
            return candidate
    return end


def find_token_sentence_start(encoding: Any, token_ids: list[int], start: int, previous_end: int) -> int:
    for candidate in range(start, previous_end):
        text = encoding.decode(token_ids[candidate:previous_end])
        if re.match(r"^\s*\S", text) and re.search(r"^[^.;:]*[.;:]\s+\S", text):
            boundary = re.search(r"[.;:]\s+(\S)", text)
            if boundary:
                prefix_tokens = len(encoding.encode(text[: boundary.start(1)]))
                return min(candidate + prefix_tokens, previous_end)
    return previous_end


def split_long_text(text: str, max_chars: int, overlap_chars: int) -> list[str]:
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
        overlap_start = max(end - overlap_chars, start + 1)
        start = find_sentence_start_near(text, overlap_start, end)
    return chunks


def find_sentence_start_near(text: str, overlap_start: int, previous_end: int) -> int:
    """Prefer a sentence boundary over a mid-word overlap start."""
    window = text[overlap_start:previous_end]
    match = re.search(r"(?:[.;:]\s+|\n+)(\S)", window)
    if match:
        return overlap_start + match.start(1)
    return previous_end


def normalize_chunk_content(content: str) -> str:
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    content = re.sub(r"[ \t]+", " ", content)
    content = re.sub(r"\n{3,}", "\n\n", content)
    return content.strip()
