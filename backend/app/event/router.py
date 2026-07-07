"""
P1 - Event Router

FastAPI router for event intake endpoints.
Handles recall event upload and triggers normalization + ticket creation.
"""

from fastapi import APIRouter, HTTPException

from app.event.normalizer import normalize_event
from app.schemas.io import EventUploadRequest, EventUploadResponse

from app.event.dedup import check_and_save_event
from app.event.ticket_creator import create_ticket
from app.event.collector import periodic_collect

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
        # 1. 정규화 데이터 생성
        event = normalize_event(payload.model_dump())

        # 2. [주석 해제] 중복 체크 실행 (수진 - dedup.py 연결 완료)
        is_dup = check_and_save_event(event.event_id)
        if is_dup:
            raise HTTPException(status_code=409, detail=f"이미 수신된 중복 이벤트입니다. (ID: {event.event_id})")

        # 3. [주석 해제] 티켓 생성 실행 (수진 - ticket_creator.py 연결 완료)
        ticket_id = create_ticket(event)

        return EventUploadResponse(
            event_id=event.event_id,
            status="received",
            ticket_id=ticket_id,
        )

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/collect", summary="openFDA 이벤트 수동 수집")
async def trigger_openfda_collection():
    """
    팀원 피드백 반영: 스케줄러 대신 사용자가 명시적으로 호출하는 수동 트리거 엔드포인트
    프론트엔드에서 'openFDA 수집 실행' 버튼 클릭 시 이 API를 호출합니다.
    수집된 각 이벤트 데이터도 정규화, 중복 체크, 티켓 생성 파이프라인을 동일하게 거치도록 보완했습니다.
    """
    print("[Router] 프론트엔드 요청으로 openFDA 수동 수집을 시작합니다...")
    
    # openFDA API 호출 및 원본 데이터 가져오기 (collector.py)
    raw_result = await periodic_collect()
    
    processed_summary = {
        "recalls": {"total_fetched": len(raw_result.get("recalls", [])), "tickets_created": 0},
        "shortages": {"total_fetched": len(raw_result.get("shortages", [])), "tickets_created": 0},
        "labels": {"total_fetched": len(raw_result.get("labels", [])), "tickets_created": 0}
    }

    # 예시: 가장 중요한 recall 데이터들을 수집 파이프라인(정규화->중복체크->티켓)에 태우는 로직 추가
    for raw_event in raw_result.get("recalls", []):
        try:
            event = normalize_event(raw_event)
            # 중복되지 않은 신규 데이터인 경우에만 티켓 발행
            if not check_and_save_event(event.event_id):
                create_ticket(event)
                processed_summary["recalls"]["tickets_created"] += 1
        except Exception:
            continue  # 한 건의 데이터가 깨져도 전체가 멈추지 않도록 예외 처리한다.

    # shortage, label도 파이프라인 확장 필요 시 위와 동일한 구조로 처리 가능합니다.

    return {
        "message": "openFDA 데이터 수동 수집 및 파이프라인 처리가 성공적으로 완료되었습니다.",
        "summary": processed_summary
    }


@router.get("/latest")
async def get_latest_events():
    """
    최근 수집된 이벤트 목록 조회.

    TODO: 2주차에 구현 (P5 DB 준비 완료 후)
    """
    return {"message": "Not implemented yet"}