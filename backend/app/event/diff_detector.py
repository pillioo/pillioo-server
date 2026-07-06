import logging
from typing import Optional, Tuple
from sqlalchemy.orm import Session

# 경로에 맞게 임포트 조정
from app.db.models.ticket import Ticket
from app.schemas.event import EventNormalized

logger = logging.getLogger(__name__)

class DiffDetector:
    def __init__(self, db: Session):
        
        # 팀원이 세팅한 실제 PostgreSQL DB 세션을 주입받는다.
        self.db = db

    def detect_difference(self, incoming_event: EventNormalized) -> Tuple[str, Optional[Ticket]]:
        # 1. FDA 고유 ID(event_id)를 기준으로 DB에서 기존 티켓을 검색한다.
        event_id = incoming_event.event_id
        
        existing_ticket = self.db.query(Ticket).filter(Ticket.openfda_id == event_id).first()
        
        # [Case 1] 완전 신규 이벤트: DB에 일치하는 openfda_id가 없음
        if not existing_ticket:
            logger.info(f"[DiffDetector] 완전 신규 이벤트 감지: {event_id}")
            return "NEW", None
            
        # [Case 2] 상태 변경 감지: 기존 티켓은 있지만, FDA 원본 상태(ongoing 등)가 바뀐 경우
        # (새로 들어온 incoming_event.status 와 DB에 저장해둔 source_status 를 비교한다.)
        if existing_ticket.source_status != incoming_event.status:
            logger.info(f"[DiffDetector] 상태 변경 감지 (Update 필요): {event_id} ({existing_ticket.source_status} -> {incoming_event.status})")
            return "STATUS_CHANGED", existing_ticket

        # [Case 3] 단순 중복: ID도 똑같고, FDA 상태도 예전과 똑같은 경우
        logger.info(f"[DiffDetector] 단순 중복 이벤트 감지 (Skip): {event_id}")
        return "DUPLICATE", existing_ticket