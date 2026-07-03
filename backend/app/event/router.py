"""
P1 - Event Router

FastAPI router for event intake endpoints.
Handles recall event upload and triggers normalization + ticket creation.
"""

from fastapi import APIRouter, HTTPException

from app.event.normalizer import normalize_event
from app.schemas.io import EventUploadRequest, EventUploadResponse

router = APIRouter(prefix="/events", tags=["events"])


@router.post("/upload", response_model=EventUploadResponse)
async def upload_event(payload: EventUploadRequest) -> EventUploadResponse:
    """
    샘플 recall 이벤트 JSON을 받아서 정규화 후 티켓 생성.

    Args:
        payload: FDA recall JSON 형식의 요청 바디

    Returns:
        EventUploadResponse: 정규화된 event_id, status, ticket_id

    예시 요청:
        POST /events/upload
        {
            "recall_number": "D-001-2026",
            "product_description": "Midazolam HCl 1mg/mL Injection, 10mL vials",
            "reason_for_recall": "Particulate matter contamination",
            "classification": "Class I",
            "product_ndc": "0641-6014-41",
            "lot_number": "LOT-A1",
            "recall_initiation_date": "2026-01-10",
            "status": "ongoing"
        }

    예시 응답:
        {
            "event_id": "D-001-2026",
            "status": "received",
            "ticket_id": "T-001"
        }
    """
    try:
        # 1. 정규화
        event = normalize_event(payload.model_dump())

        # 2. TODO: dedup 체크 (수진 - dedup.py 완성 후 연결)
        # is_dup = check_duplicate(event.event_id)
        # if is_dup:
        #     raise HTTPException(status_code=409, detail="Duplicate event")

        # 3. TODO: 티켓 생성 (수진 - ticket_creator.py 완성 후 연결)
        # ticket_id = create_ticket(event)
        ticket_id = f"T-{event.event_id}"  # 임시 mock

        return EventUploadResponse(
            event_id=event.event_id,
            status="received",
            ticket_id=ticket_id,
        )

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/latest")
async def get_latest_events():
    """
    최근 수집된 이벤트 목록 조회.

    TODO: 2주차에 구현 (P5 DB 준비 완료 후)
    """
    # TODO: DB에서 최근 이벤트 조회
    return {"message": "Not implemented yet"}
