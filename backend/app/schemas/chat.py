from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.evidence import Citation


class ChatMessage(BaseModel):
    ticket_id: str = Field(..., min_length=1)
    session_id: Optional[str] = Field(default=None, min_length=1)
    role: Literal["user", "assistant"]
    content: str
    retrieved_sources: list[Citation] = Field(default_factory=list)
    created_at: datetime
    # "succeeded" | "failed". Failed assistant turns are now persisted
    # instead of being silently rolled back (see app.chat.handler.handle_chat).
    status: Literal["succeeded", "failed"] = "succeeded"