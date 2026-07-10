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
    return OpenAI()


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
    약사가 특정 티켓에 대해 근거 문서를 질의.

    - session_id 없으면 이 ticket의 기존 세션을 재사용 (없으면 새로 생성)
    - RetrievalService로 관련 evidence 검색 (recall_number_is_fallback 반영)
    - evidence가 있으면 LLM이 세션 히스토리 + ticket 상태 요약 + evidence로 답변 생성
    - evidence가 없으면 고정 fallback 메시지 반환
    - user/assistant 메시지 chat_messages 테이블에 저장

    예시 요청:
        POST /chat/T-001
        {
            "user_query": "격리 절차 근거 보여줘",
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
    특정 티켓의 전체 채팅 기록 반환 (시간순).
    ticket당 세션이 하나이므로 이는 그 세션의 전체 기록과 같다.
    """
    return get_chat_history(
        db=db,
        public_ticket_id=ticket_id,
    )
