from threading import Lock
from app.event.schema import DedupResponse

# 1주차 MVP용 임시 데이터베이스 (메모리에 event_id 저장)
# 프로그램이 실행되는 동안 중복 여부를 기억한다.
_mock_processed_events = set()
_mock_processed_events_lock = Lock()

def check_and_save_event(event_id: str) -> DedupResponse:

    with _mock_processed_events_lock:

        # 1. 중복 검사: 이미 저장소에 ID가 존재하는 경우
        if event_id in _mock_processed_events:
            return DedupResponse(duplicated=True)

        # 2. 신규 이벤트: 저장소에 ID를 추가하고 중복 없음(False)으로 반환
        _mock_processed_events.add(event_id)
        return DedupResponse(duplicated=False)

# --- 개발자용 로컬 테스트 코드 ---
if __name__ == "__main__":
    # Pydantic 객체는 json.dumps 없이 .model_dump()나 .model_dump_json()으로 바로 출력할 수 있습니다.
    print("=== 테스트 1: 신규 이벤트 수신 ===")
    test_1 = check_and_save_event("FDA-2026-001")
    print(f"입력: FDA-2026-001 -> 결과: {test_1.model_dump_json()}")
    # 예상 결과: {"duplicated": false}
    
    print("\n=== 테스트 2: 똑같은 이벤트 다시 수신 ===")
    test_2 = check_and_save_event("FDA-2026-001")
    print(f"입력: FDA-2026-001 -> 결과: {test_2.model_dump_json()}")
    # 예상 결과: {"duplicated": true}
    
    print("\n=== 테스트 3: 다른 신규 이벤트 수신 ===")
    test_3 = check_and_save_event("FDA-2026-002")
    print(f"입력: FDA-2026-002 -> 결과: {test_3.model_dump_json()}")
    # 예상 결과: {"duplicated": false}