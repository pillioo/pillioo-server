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

    # diff_detector가 FDA 상태 변화를 비교할 수 있도록 원본 status 보존
    source_status: str = Field(..., description="Ticket 생성 시점의 FDA 원본 status (예: ongoing, terminated)")

    # --- RAG/Evidence 연동을 위해 추가된 추적용 데이터 ---
    # EventNormalized에서 required로 보장되는 필드이므로 여기서도 required로 맞춤.
    recall_number: str = Field(..., description="FDA 리콜 번호")
    product_description: str = Field(..., description="제품 상세 설명")
    reason_for_recall: Optional[str] = Field(default=None, description="리콜 사유 원본 텍스트")
    openfda_id: Optional[str] = Field(default=None, description="OpenFDA 고유 ID 또는 Source ID")

    source_status: Optional[str] = Field(default=None, description="FDA 원본 상태 (ongoing 등)")

# --- 중복 검사 결과 모델 ---
class DedupResponse(BaseModel):
    duplicated: bool