import json
import pytest
from datetime import datetime, timezone
from pathlib import Path
from pydantic import ValidationError

# 프로젝트 경로에 맞게 임포트한다.
from app.event.schema import Ticket 

def test_ticket_schema_with_complex_edge_case():
    
    # 복합 엣지 케이스 JSON 데이터를 사용하여 Ticket 스키마 검증 및 DB 모델 호환성을 테스트한다.
    
    # 1. 복합 엣지 케이스 JSON 데이터 불러오기
    file_path = Path(__file__).parent / 'complex_edge_case.json'
    with open(file_path, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)

    # 2. 실제 ticket_creator.py가 조립하는 방식과 똑같이 Payload 구성
    test_payload = {
        "ticket_id": "TICKET-TEST-002",
        "event_type": "recall",
        "drug_name": "Midazolam HCl",
        "ndc": raw_data.get("product_ndc", "0000-0000-00"),
        "created_at": datetime.now(timezone.utc),
        
        # FDA 원본 상태를 저장하는 필드
        "source_status": "ongoing", 
        
        **raw_data
    }

    # 3. Pydantic 스키마(Ticket)에 데이터 통과시키기 및 검증 (assert)
    try:
        ticket = Ticket(**test_payload)
        
        # 4. 검증 (assert): 우리가 기대한 값들이 티켓 객체에 잘 들어갔는지 확인
        assert ticket.ticket_id == "TICKET-TEST-002"
        assert ticket.event_type.value == "recall"
        assert ticket.drug_name == "Midazolam HCl"
        # source_status가 제대로 저장되었는지 명시적으로 확인
        assert ticket.source_status == "ongoing" 
        
    except ValidationError as e:
        # 스키마 통과에 실패하면 테스트를 강제로 실패(fail) 처리하고 에러를 보여줌
        pytest.fail(f"스키마 검증 실패: {e}")

