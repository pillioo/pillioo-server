"""
Evidence Chat Router

FastAPI router for Evidence Chat endpoints.

Endpoints:
    POST /chat/{ticket_id}          → submit a query and get citation-included answer
    GET  /chat/{ticket_id}/history  → get full chat history for a ticket
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.chat.handler import get_chat_history, handle_chat
from app.core.config import settings
from app.db.session import get_db
from app.rag.service import RetrievalService

router = APIRouter(tags=["chat"])


def get_retrieval_service() -> RetrievalService:
    return RetrievalService.from_milvus(
        uri=settings.MILVUS_URI,
        collection_name=settings.MILVUS_COLLECTION,
        embedding_model=settings.EMBEDDING_MODEL,
    )


class ChatRequest(BaseModel):
    user_query: str = Field(..., min_length=1, description="Pharmacist's question")
    session_id: str | None = Field(default=None, description="Existing session ID (creates new if not provided)")
    top_k: int = Field(default=5, ge=1, le=20, description="Number of evidence chunks to retrieve")


# ──────────────────────────────────────────────
# Chat Endpoints
# ──────────────────────────────────────────────

@router.post("/chat/{ticket_id}")
async def submit_chat_query(
    ticket_id: str,
    request: ChatRequest,
    db: Session = Depends(get_db),
    retrieval_service: RetrievalService = Depends(get_retrieval_service),
):
    """
    약사가 특정 티켓에 대해 근거 문서를 질의.

    - session_id 없으면 새 세션 생성
    - RetrievalService로 관련 evidence 검색
    - citation 포함 답변 반환
    - user/assistant 메시지 chat_messages 테이블에 저장

    예시 요청:
        POST /chat/T-001
        {
            "user_query": "격리 절차 근거 보여줘",
            "session_id": null
        }

    예시 응답:
        {
            "session_id": "abc-123",
            "answer": "Based on the retrieved evidence for midazolam: ...",
            "sources": [
                {
                    "source": "recall_sop.md",
                    "section": "quarantine_procedure",
                    "score": 0.91,
                    "content": "..."
                }
            ]
        }
    """
    return handle_chat(
        db=db,
        public_ticket_id=ticket_id,
        user_query=request.user_query,
        session_id=request.session_id,
        retrieval_service=retrieval_service,
        top_k=request.top_k,
    )


@router.get("/chat/{ticket_id}/history")
async def get_ticket_chat_history(
    ticket_id: str,
    db: Session = Depends(get_db),
):
    """
    특정 티켓의 전체 채팅 기록 반환 (시간순).

    예시 응답:
        [
            {
                "role": "user",
                "content": "격리 절차 근거 보여줘",
                "retrieved_sources": [],
                "created_at": "2026-07-01T10:00:00"
            },
            {
                "role": "assistant",
                "content": "Based on the retrieved evidence...",
                "retrieved_sources": [...],
                "created_at": "2026-07-01T10:00:02"
            }
        ]
    """
    return get_chat_history(
        db=db,
        public_ticket_id=ticket_id,
    )
