from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.evidence import Citation


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    retrieved_sources: list[Citation] = Field(default_factory=list)
    created_at: datetime