"""
Evidence Chat Handler

Handles pharmacist chat queries against a specific ticket's evidence context.
Calls RAG RetrievalService to find relevant evidence and returns citation-included answers.

Pipeline position: after review payload is shown to pharmacist,
pharmacist can query evidence documents via chat.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models.chat import ChatSession, ChatMessage
from app.orchestration.state import ticket_to_state
from app.rag.models import RetrievalContext
from app.rag.service import RetrievalService
from app.review.errors import ReviewError, raise_review_error
from app.review.tickets import get_ticket_by_public_id
from app.schemas.chat import ChatMessage as ChatMessageSchema


def get_or_create_session(
    db: Session,
    ticket_id: int,
    session_id: str | None,
) -> ChatSession:
    """
    session_id가 없으면 새 세션 생성.
    있으면 기존 세션 반환.
    """
    if session_id:
        session = db.query(ChatSession).filter(
            ChatSession.session_id == session_id,
            ChatSession.ticket_id == ticket_id,
        ).first()
        if not session:
            raise_review_error(
                ReviewError.REVIEW_NOT_FOUND,
                {"session_id": session_id, "reason": "Session not found"}
            )
        return session

    session = ChatSession(
        session_id=str(uuid.uuid4()),
        ticket_id=ticket_id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(session)
    db.flush()
    db.refresh(session)
    return session


def save_message(
    db: Session,
    ticket_id: int,
    session_id: str,
    role: str,
    content: str,
    retrieved_sources: list[dict] | None = None,
) -> ChatMessage:
    """
    chat_messages 테이블에 메시지 저장.
    """
    message = ChatMessage(
        ticket_id=ticket_id,
        session_id=session_id,
        role=role,
        content=content,
        retrieved_sources=retrieved_sources or [],
        created_at=datetime.now(timezone.utc),
    )
    db.add(message)
    db.flush()
    db.refresh(message)
    return message


def handle_chat(
    db: Session,
    public_ticket_id: str,
    user_query: str,
    session_id: str | None,
    retrieval_service: RetrievalService,
    top_k: int = 5,
) -> dict:
    """
    약사 채팅 질의 처리.

    1. ticket 조회 → TicketState 변환
    2. 세션 생성 또는 기존 세션 사용
    3. user 메시지 저장
    4. RetrievalService.retrieve() 호출
    5. 검색 결과로 template 답변 구성
    6. assistant 메시지 저장
    7. 응답 반환

    Args:
        db: DB 세션
        public_ticket_id: 공개 티켓 ID (e.g. "T-XXXX")
        user_query: 약사 질문
        session_id: 기존 세션 ID (없으면 새로 생성)
        retrieval_service: RAG RetrievalService 인스턴스
        top_k: 검색 결과 수

    Returns:
        dict:
            - session_id: 세션 ID
            - answer: 답변 텍스트
            - sources: citation 목록

    예시 응답:
        {
            "session_id": "abc-123",
            "answer": "Based on the retrieved evidence: ...",
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
    # 1. ticket 조회 → TicketState 변환
    ticket = get_ticket_by_public_id(db, public_ticket_id)
    state = ticket_to_state(ticket)

    # 2. 세션 생성 또는 기존 세션 사용
    session = get_or_create_session(db, ticket.id, session_id)

    # 3. user 메시지 저장
    save_message(
        db=db,
        ticket_id=ticket.id,
        session_id=session.session_id,
        role="user",
        content=user_query,
    )

    # 4. RetrievalService.retrieve() 호출
    context = RetrievalContext(
        event_type=state.event_type.value if state.event_type else None,
        query=user_query,
        drug_name=state.event_normalized.drug_name if state.event_normalized else None,
        normalized_drug_name=state.event_normalized.drug_name if state.event_normalized else None,
        ndc=[state.event_normalized.ndc] if state.event_normalized and state.event_normalized.ndc else [],
        lot=state.event_normalized.lot if state.event_normalized else None,
        recall_number=state.event_normalized.recall_number if state.event_normalized else None,
        classification=state.classification.value if state.classification else None,
    )

    evidence_result = retrieval_service.retrieve(
        query=user_query,
        context=context,
        top_k=top_k,
    )

    # 5. template 답변 구성 (MVP — LLM 생성은 후순위)
    sources = [
        {
            "source": chunk.source_path,
            "section": chunk.section,
            "score": round(chunk.score, 4),
            "content": chunk.content[:300],  # 미리보기 300자
        }
        for chunk in evidence_result.chunks[:top_k]
    ]

    if sources:
        answer = (
            f"Based on the retrieved evidence for {state.event_normalized.drug_name if state.event_normalized else 'this drug'}: "
            f"Found {len(sources)} relevant document(s). "
            "Please review the sources below and consult the pharmacist for final decision."
        )
    else:
        answer = (
            "No relevant evidence found for your query. "
            "Please consult the pharmacist directly or broaden your search."
        )

    # 6. assistant 메시지 저장
    save_message(
        db=db,
        ticket_id=ticket.id,
        session_id=session.session_id,
        role="assistant",
        content=answer,
        retrieved_sources=sources,
    )

    db.commit()

    # 7. 응답 반환
    return {
        "session_id": session.session_id,
        "answer": answer,
        "sources": sources,
    }


def get_chat_history(
    db: Session,
    public_ticket_id: str,
) -> list[dict]:
    """
    특정 티켓의 전체 채팅 기록 반환.

    Args:
        db: DB 세션
        public_ticket_id: 공개 티켓 ID

    Returns:
        list[dict]: 메시지 목록 (시간순)
    """
    ticket = get_ticket_by_public_id(db, public_ticket_id)

    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.ticket_id == ticket.id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )

    return [
        {
            "role": msg.role,
            "content": msg.content,
            "retrieved_sources": msg.retrieved_sources or [],
            "created_at": msg.created_at,
        }
        for msg in messages
    ]
