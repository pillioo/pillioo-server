from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

# 사전 정의된 표준 스키마를 가져온다.
from app.schemas.event import EventNormalized
from app.schemas.common import EventType, Classification, TicketStatus

# --- 최종 티켓 모델 ---
class Ticket(BaseModel):
    ticket_id: str
    event_type: EventType
    drug_name: str
    ndc: str
    lot: Optional[str] = None
    classification: Optional[Classification] = None
    priority: Optional[str] = None
    status: TicketStatus = TicketStatus.CREATED  # 문자열 대신 공통 Enum 규격 사용
    
    # (피드백 반영 부분) 다음 작업 스테이지 명시
    workflow_stage: str = Field(default="PENDING_INVENTORY", description="다음 작업 대기 상태 (예: PENDING_INVENTORY, PENDING_RAG)")
    
    created_at: datetime

    # --- RAG/Evidence 연동을 위해 추가된 추적용 데이터 --- 
    recall_number: Optional[str] = Field(default=None, description="FDA 리콜 번호")
    reason_for_recall: Optional[str] = Field(default=None, description="리콜 사유 원본 텍스트")
    product_description: Optional[str] = Field(default=None, description="제품 상세 설명")
    openfda_id: Optional[str] = Field(default=None, description="OpenFDA 고유 ID 또는 Source ID")

    source_status: Optional[str] = Field(default=None, description="FDA 원본 상태 (ongoing 등)")

# --- 중복 검사 결과 모델 ---
class DedupResponse(BaseModel):
    duplicated: bool