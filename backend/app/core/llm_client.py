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
    helper -- they construct their own bare OpenAI() client and always call
    the OpenAI API directly, since a chat-completions gateway is not
    guaranteed to also proxy the embeddings endpoint.
    """
    return OpenAI(**openai_client_kwargs())
