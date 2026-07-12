"""
Chat DB Models

SQLAlchemy models for Evidence Chat sessions and messages.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from app.db.base import TimeStampedModel


class ChatSession(TimeStampedModel):
    __tablename__ = "chat_sessions"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'closed')", name="chat_sessions_status_check"),
    )

    session_id = Column(String, unique=True, nullable=False, index=True)
    ticket_id = Column(
        Integer,
        ForeignKey("tickets.id"),
        nullable=False,
        index=True,
    )
    # "active" | "closed". No close-session endpoint exists yet -- this is
    # schema support for a future lifecycle action; every session is
    # currently "active" for its whole life.
    status = Column(String, nullable=False, default="active", server_default="active")


class ChatMessage(TimeStampedModel):
    __tablename__ = "chat_messages"
    __table_args__ = (
        CheckConstraint("status IN ('succeeded', 'failed')", name="chat_messages_status_check"),
    )

    ticket_id = Column(
        Integer,
        ForeignKey("tickets.id"),
        nullable=False,
        index=True,
    )
    session_id = Column(
        String,
        ForeignKey("chat_sessions.session_id"),
        nullable=False,
        index=True,
    )
    role = Column(String, nullable=False)          # "user" or "assistant"
    content = Column(Text, nullable=False)
    retrieved_sources = Column(JSONB, nullable=True)
    # "succeeded" | "failed". User messages are always "succeeded" (saving
    # the question can't itself fail in a meaningful way); assistant
    # messages are "failed" when retrieval/LLM processing errored out, so a
    # failed turn is still visible in chat history instead of vanishing.
    status = Column(String, nullable=False, default="succeeded", server_default="succeeded")