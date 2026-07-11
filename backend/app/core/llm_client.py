from __future__ import annotations

from openai import OpenAI

from app.core.config import settings


def openai_client_kwargs() -> dict[str, str]:
    """Kwargs needed to route an OpenAI() client through an OpenAI-compatible
    gateway (e.g. a Claude-backed proxy) instead of api.openai.com, based on
    settings.OPENAI_API_KEY / OPENAI_BASE_URL.

    Returns an empty dict when neither is configured, so `OpenAI(**kwargs)`
    behaves exactly like bare `OpenAI()` (falls back to the SDK's own env
    lookup / api.openai.com default).
    """
    kwargs: dict[str, str] = {}
    if settings.OPENAI_API_KEY:
        kwargs["api_key"] = settings.OPENAI_API_KEY
    if settings.OPENAI_BASE_URL:
        kwargs["base_url"] = settings.OPENAI_BASE_URL
    return kwargs


def build_llm_client() -> OpenAI:
    """Build the OpenAI-compatible client used for chat/completion calls
    (draft generation, evidence chat).

    Embeddings (app/rag, scripts/rag/embedding) intentionally do NOT use this
    helper -- see embedding_client_kwargs() below.
    """
    return OpenAI(**openai_client_kwargs())


_OPENAI_API_BASE_URL = "https://api.openai.com/v1"


def embedding_client_kwargs() -> dict[str, str]:
    """Kwargs for the embeddings client. Embeddings always call the real
    OpenAI API directly -- never through OPENAI_BASE_URL -- because a
    chat-completions gateway is not guaranteed to also proxy /embeddings.

    IMPORTANT: a "bare" `OpenAI()` call is NOT actually gateway-free once
    OPENAI_BASE_URL is set as an environment variable, because the OpenAI
    SDK falls back to reading OPENAI_BASE_URL from the environment itself
    when no explicit base_url is passed. That silently rerouted embedding
    requests through the chat gateway and produced 404s (the gateway has
    no /embeddings route). This function always pins base_url explicitly
    to bypass that fallback.

    Uses settings.EMBEDDING_API_KEY if set (needed once OPENAI_API_KEY has
    been repurposed as a gateway key), else falls back to OPENAI_API_KEY.
    """
    kwargs: dict[str, str] = {"base_url": _OPENAI_API_BASE_URL}
    api_key = settings.EMBEDDING_API_KEY or settings.OPENAI_API_KEY
    if api_key:
        kwargs["api_key"] = api_key
    return kwargs
