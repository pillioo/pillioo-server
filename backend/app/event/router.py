"""
Event Router

FastAPI router for event intake endpoints.
Handles recall event upload and triggers normalization + dedup + ticket creation.
"""
import hashlib
import json
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models.ticket import Ticket
from app.event.normalizer import normalize_event
from app.schemas.io import EventUploadRequest, EventUploadResponse, EventFeedItem, EventLatestResponse

from app.event.dedup import check_and_save_event, release_event
from app.orchestration.tickets import get_or_create_ticket_record
from app.event.collector import periodic_collect
from app.workflow.state import can_rerun_workflow

router = APIRouter(prefix="/events", tags=["events"])

# 식별자가 없을 때 원본 데이터를 해싱하여 안정적인 고유 ID 생성
def generate_fallback_id(data: dict) -> str:
    # 딕셔너리 키를 정렬하여 항상 일정한 문자열이 나오도록 보장
    payload_str = json.dumps(data, sort_keys=True)
    hash_val = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()[:12]
    return f"FALLBACK-{hash_val}"

@router.post("/upload", response_model=EventUploadResponse)
async def upload_event(
    payload: EventUploadRequest,
    db: Session = Depends(get_db),
) -> EventUploadResponse:
    """
    샘플 recall 이벤트 JSON을 받아서 정규화, 중복 체크 후 티켓 생성.
    """
    try:

        # 1. 페이로드(입력값)를 딕셔너리로 변환
        raw_data = payload.model_dump(mode="json")
        
        # 1번 스키마와 2번 Normalizer 사이의 통역사 역할
        # 스키마를 통과한 소문자 class 데이터를 Normalizer가 좋아하는 FDA 원본 형식으로 바꿔줍니다.
        class_mapping = {
            "class_i": "Class I",
            "class_ii": "Class II",
            "class_iii": "Class III"
        }
        current_class = raw_data.get("classification")
        if current_class in class_mapping:
            raw_data["classification"] = class_mapping[current_class]

        # 통역된 데이터로 정규화 실행
        event = normalize_event(raw_data)

        # 2. 중복 체크
        dedup_result = check_and_save_event(event.event_id)
        if dedup_result.duplicated:
            raise HTTPException(
                status_code=409,
                detail={
                    "error_code": "DUPLICATE_EVENT",
                    "message": "Event already processed",
                    "detail": {"event_id": event.event_id}
                }
            )

        # 3. 티켓 생성 — Postgres에 영속화 (실패 시 원자성을 위해 rollback + release_event)
        try:
            # orchestration 파이프라인과 동일하게 실제 DB에 upsert 합니다.
            ticket, _created = get_or_create_ticket_record(db, event)
            db.commit()
        except Exception as e:
            db.rollback()
            release_event(event.event_id) # 중복 저장했던 기록 취소
            raise HTTPException(
                status_code=500,
                detail={
                    "error_code": "INTERNAL_SERVER_ERROR",
                    "message": "Failed to create ticket"
                }
            ) from e

        # 4. 피드백 반영: status 제거, duplicated 추가, ticket.id 문자열 추출
        return EventUploadResponse(
            event_id=event.event_id,
            duplicated=False,
            ticket_id=ticket.ticket_id if ticket else None
        )

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/collect", summary="openFDA 이벤트 수동 수집")
async def trigger_openfda_collection(db: Session = Depends(get_db)):
    """
    스케줄러 대신 사용자가 명시적으로 호출하는 수동 트리거 엔드포인트.
    프론트엔드에서 'openFDA 수집 실행' 버튼 클릭 시 이 API를 호출합니다.
    """
    print("[Router] 프론트엔드 요청으로 openFDA 수동 수집을 시작합니다...")
    
    # openFDA API 호출 및 원본 데이터 가져오기 (collector.py)
    raw_result = await periodic_collect()
    
    processed_summary = {
        "recalls": {"total_fetched": len(raw_result.get("recalls", [])), "tickets_created": 0},
        "shortages": {"total_fetched": len(raw_result.get("shortages", [])), "tickets_created": 0},
        "labels": {"total_fetched": len(raw_result.get("labels", [])), "tickets_created": 0}
    }

    # 수집된 대량의 recall 데이터를 안전하게 파이프라인에 태우기
    for raw_event in raw_result.get("recalls", []):
        try:
            # 1. 정규화
            event = normalize_event(raw_event)

            # [코드래빗 피드백 반영] 대량 수집 시에도 UNKNOWN_ID 충돌 방지
            if event.event_id == "UNKNOWN_ID":
                event.event_id = generate_fallback_id(raw_event)
            
            # 2. 수동 수집 루프에서도 .duplicated 필드를 보도록 수정 완료!
            dedup_result = check_and_save_event(event.event_id)
            if not dedup_result.duplicated:
                try:
                    _ticket, created = get_or_create_ticket_record(db, event)
                    db.commit()
                    if created:
                        processed_summary["recalls"]["tickets_created"] += 1
                except Exception as e:
                    db.rollback()
                    print(f"[Router] 티켓 생성 실패, 롤백합니다: {event.event_id}, error={e}")
                    release_event(event.event_id) # 티켓 발행 실패 시 롤백
        except Exception as e:
            print(f"[Router] recall 이벤트 처리 실패, 건너뜁니다: {raw_event.get('recall_number')}, error={e}")
            continue  # 한 건의 데이터가 포맷 오류 등으로 깨져도 전체 수집이 멈추지 않도록 방어

    return {
        "message": "openFDA 데이터 수동 수집 및 파이프라인 처리가 성공적으로 완료되었습니다.",
        "summary": processed_summary
    }




@router.get("/latest")
async def get_latest_events(
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """
    최근 수집된 이벤트 목록 조회.
    티켓 생성 시간 기준 최신순으로 반환.
    """

    total_ticket_count = db.query(Ticket).count()

    tickets = (
        db.query(Ticket)
        .order_by(Ticket.created_at.desc())
        .limit(limit)
        .all()
    )

    feed_items = []
    for ticket in tickets:
        # 1. 상태값을 문자열로 안전하게 추출
        status_val = ticket.status.value if hasattr(ticket.status, "value") else ticket.status
        
        # 2. 오케스트레이터의 공통 정책 함수를 그대로 재사용! (핵심)
        can_run = can_rerun_workflow(status_val)

        feed_items.append(
            EventFeedItem(
                event_id=ticket.openfda_id or f"fallback-{ticket.ticket_id}",
                source="openFDA" if ticket.openfda_id else "manual_upload",
                is_duplicate=None, 
                product_description=ticket.product_description or ticket.drug_name,
                recall_reason=ticket.reason_for_recall,
                ticket_id=ticket.ticket_id,
                
                # 3. 계산된 값을 프론트엔드에 전달
                can_run=can_run,
                
                raw_event_data={
                    "drug_name": ticket.drug_name,
                    "ndc": ticket.ndc,
                    "classification": getattr(ticket.classification, "value", ticket.classification) if ticket.classification else None,
                    "event_type": getattr(ticket.event_type, "value", ticket.event_type) if ticket.event_type else None,
                    "status": status_val,
                    "workflow_stage": ticket.workflow_stage,
                },
                created_at=ticket.created_at
            )
        )

    return EventLatestResponse(events=feed_items, total_count=total_ticket_count)