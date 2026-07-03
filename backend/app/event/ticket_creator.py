import uuid
from datetime import datetime, timezone

from app.schemas.common import TicketStatus, EventType, Classification
from app.schemas.event import EventNormalized
from app.event.schema import Ticket

# 1주차 MVP용 임시 데이터베이스 (메모리에 티켓 저장)
_mock_tickets_db = {}

def create_ticket(event_data: EventNormalized) -> Ticket:

    # 1. 고유한 티켓 ID 생성 (예: T- + 고유번호)
    +    ticket_id = f"T-{uuid.uuid4().hex.upper()}"
    
    # 2. 현재 시간 기록 (UTC 기준)
    created_at = datetime.now(timezone.utc)

    # 3. 티켓 데이터 조립 (RAG/Evidence 연동 필드 추가)
    new_ticket = Ticket(
        ticket_id=ticket_id,
        event_type=event_data.event_type, 
        drug_name=event_data.drug_name,
        ndc=event_data.ndc,
        lot=event_data.lot,
        classification=event_data.classification,
        priority=None, # P2 결과가 나오면 채워질 필드
        status=TicketStatus.CREATED,

        # 생성 직후 다음 단계로 '재고 매칭'을 지시한다. (수정사항)
        workflow_stage="PENDING_INVENTORY", 
        
        created_at=created_at,
        
        # event_data에 필드가 없을 경우를 안전하게 대비한다.
        recall_number=getattr(event_data, "recall_number", None),
        reason_for_recall=getattr(event_data, "reason_for_recall", None),
        product_description=getattr(event_data, "product_description", None),
        openfda_id=getattr(event_data, "event_id", None)  # 원본 event_id를 소스 ID로 활용
    )

    # 4. 임시 DB에 저장
    _mock_tickets_db[ticket_id] = new_ticket

    return new_ticket


# --- 개발자용 로컬 테스트 코드 ---
if __name__ == "__main__":
    from datetime import date

    # EventNormalized 스키마 규칙에 맞춰 테스트 데이터를 만든다.
    mock_event = EventNormalized(
        event_id="FDA-2026-001",
        event_type=EventType.RECALL,
        drug_name="MIDAZOLAM", # 소문자로 자동 정교화
        ndc="00641601441", # 정확히 11자리 숫자 기입
        lot="LOT-A",
        classification=Classification.CLASS_I,
        status="ongoing",
        recall_initiation_date=date(2026, 6, 1)
    )
    
    print("=== 티켓 생성 테스트 (RAG 연동 데이터 포함) ===")
    ticket_result = create_ticket(mock_event)
    
    # 생성된 최종 티켓 구조 출력
    print(ticket_result.model_dump_json(indent=2))