import json
from datetime import datetime, timezone
from pydantic import ValidationError

# 수진님의 프로젝트 경로에 맞게 임포트
from app.event.schema import Ticket 

# 1. 복합 엣지 케이스 JSON 데이터 불러오기
# (경로가 다를 경우 'complex_edge_case.json'이 있는 위치로 수정해주세요)
with open('app/event/complex_edge_case.json', 'r', encoding='utf-8') as f:
    raw_data = json.load(f)

print("🔍 스키마 검증 및 DB 모델 호환성 테스트를 시작합니다...\n")

try:
    # 2. 실제 ticket_creator.py가 조립하는 방식과 똑같이 Payload 구성
    test_payload = {
        "ticket_id": "TICKET-TEST-002",
        "event_type": "recall",
        "drug_name": "Midazolam HCl",
        "ndc": raw_data.get("product_ndc", "0000-0000-00"),
        "created_at": datetime.now(timezone.utc),
        
        # 🌟 이번에 해결한 논리적 구멍! FDA 원본 상태를 저장하는 필드
        "source_status": "ongoing", 
        
        **raw_data
    }

    # 3. Pydantic 스키마(Ticket)에 데이터 통과시키기
    ticket = Ticket(**test_payload)
    
    print("✅ 테스트 성공! 업데이트된 스키마를 무사히 통과했습니다.")
    print("--- 생성된 Ticket 객체 ---")
    print(ticket.model_dump_json(indent=2))

except ValidationError as e:
    print("❌ 삐빅! 에러 발생 (ValidationError):")
    print(e)

