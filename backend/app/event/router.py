from app.event.dedup import check_and_save_event, release_event

@router.post("/upload", response_model=EventUploadResponse)
async def upload_event(payload: EventUploadRequest) -> EventUploadResponse:
    try:
        # 1. 정규화 (mode="json"으로 날짜 ISO 문자열 변환)
        event = normalize_event(payload.model_dump(mode="json"))

        # 2. 중복 체크 + 저장 (원자적으로 한 번에)
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

        # 3. 티켓 생성 — 실패 시 rollback
        try:
            ticket = create_ticket(event)
        except Exception as e:
            release_event(event.event_id)  # 예약 취소
            raise HTTPException(status_code=500, detail={
                "error_code": "INTERNAL_SERVER_ERROR",
                "message": "Failed to create ticket",
                "detail": str(e)
            })

        # 4. duplicated: False 명시
        return EventUploadResponse(
            event_id=event.event_id,
            status="received",
            ticket_id=ticket.ticket_id,
            duplicated=False,
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))