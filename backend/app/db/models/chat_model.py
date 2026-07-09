"""
Chat DB Models

SQLAlchemy models for Evidence Chat sessions and messages.
"""

from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from app.db.base import TimeStampedModel


class ChatSession(TimeStampedModel):
    __tablename__ = "chat_sessions"

    session_id = Column(String, unique=True, nullable=False, index=True)
    ticket_id = Column(
        Integer,
        ForeignKey("tickets.id"),
        nullable=False,
        index=True,
    )


class ChatMessage(TimeStampedModel):
    __tablename__ = "chat_messages"

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