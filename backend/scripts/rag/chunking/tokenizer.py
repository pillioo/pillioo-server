from __future__ import annotations

from functools import lru_cache
from typing import Any

from scripts.rag.chunking.config import EMBEDDING_MODEL, TOKEN_ENCODING_NAME

try:
    import tiktoken
except ImportError:  # pragma: no cover
    tiktoken = None


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
