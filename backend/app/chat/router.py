"""
Evidence Chat Router

FastAPI router for Evidence Chat endpoints.

Endpoints:
    POST /chat/{ticket_id}          -> submit a query and get citation-included answer
    GET  /chat/{ticket_id}/history  -> get full chat history for a ticket
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from openai import OpenAI
from sqlalchemy.orm import Session

from app.chat.handler import get_chat_history, handle_chat
from app.core.config import settings
from app.core.llm_client import build_llm_client
from app.db.session import get_db
from app.rag.service import RetrievalService
from app.schemas.chat import ChatMessage as ChatMessageSchema
from app.schemas.io import ChatRequest, ChatResponse

router = APIRouter(tags=["chat"])


def get_retrieval_service() -> RetrievalService:
    return RetrievalService.from_milvus(
        uri=settings.MILVUS_URI,
        collection_name=settings.MILVUS_COLLECTION,
        embedding_model=settings.EMBEDDING_MODEL,
    )


def get_llm_client() -> OpenAI:
    return build_llm_client()


# ----------------------------------------------
# Chat Endpoints
# ----------------------------------------------

@router.post("/chat/{ticket_id}", response_model=ChatResponse)
def submit_chat_query(
    ticket_id: str,
    request: ChatRequest,
    db: Session = Depends(get_db),
    retrieval_service: RetrievalService = Depends(get_retrieval_service),
    llm_client: OpenAI = Depends(get_llm_client),
) -> ChatResponse:
    """
    Pharmacist queries evidence documents for a specific ticket.

    - If session_id is absent, reuse this ticket's existing session (create one if none exists).
    - Search relevant evidence via RetrievalService (honors recall_number_is_fallback).
    - If evidence was found, the LLM answers using session history + ticket state summary + evidence.
    - If no evidence was found, return the fixed fallback message.
    - Save the user/assistant messages to chat_messages.

    Example request:
        POST /chat/T-001
        {
            "user_query": "Show me the evidence for the quarantine procedure",
            "session_id": null
        }
    """
    result = handle_chat(
        db=db,
        public_ticket_id=ticket_id,
        user_query=request.user_query,
        session_id=request.session_id,
        retrieval_service=retrieval_service,
        top_k=request.top_k,
        llm_client=llm_client,
    )
    return ChatResponse(**result)


@router.get("/chat/{ticket_id}/history", response_model=list[ChatMessageSchema])
def get_ticket_chat_history(
    ticket_id: str,
    db: Session = Depends(get_db),
) -> list[ChatMessageSchema]:
    """
    Return the full chat history for a ticket (chronological order).
    Since there is one session per ticket, this is equivalent to that
    session's full history.
    """
    return get_chat_history(
        db=db,
        public_ticket_id=ticket_id,
    )
