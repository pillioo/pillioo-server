# Event Collector (Full Implementation)
# openFDA API(Recall, Shortage, Label) 비동기 수집 모듈
# MVP 지원: 로컬 테스트 함수와 실제 API 연동 로직 통합

import os
import json
import httpx
from pathlib import Path
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# .env 파일 로드 (API 키 환경 변수 적용)
load_dotenv()

# openFDA API 엔드포인트
OPENFDA_RECALL_URL = "https://api.fda.gov/drug/enforcement.json"
OPENFDA_SHORTAGE_URL = "https://api.fda.gov/drug/shortages.json"
OPENFDA_LABEL_URL = "https://api.fda.gov/drug/label.json"

# API 키 설정 (없어도 기본 제한 내에서 호출 가능)
OPENFDA_API_KEY = os.getenv("OPENFDA_API_KEY")

# 샘플 데이터 경로 설정 (__file__ 기준)
SAMPLE_DATA_PATH = Path(__file__).parent.parent.parent.parent / "data" / "event" / "recall_samples.json"


# API 키가 있으면 파라미터에 추가해 호출 제한(Rate Limit)을 해제한다.
def _get_auth_params(base_params: dict) -> dict:
    params = base_params.copy()
    if OPENFDA_API_KEY:
        params["api_key"] = OPENFDA_API_KEY
    return params


# 1. openFDA에서 최근 N일(기본 7일)간의 recall 이벤트를 비동기로 수집한다.
# Args: limit(최대 이벤트 수), days(조회 기간)
# Returns: recall 이벤트 목록 (list[dict])

# openFDA에서 최근 N일(기본 90일로 연장)간의 recall 이벤트를 비동기로 수집
async def fetch_recall_events(limit: int = 10, days: int = 90) -> list[dict]:
    today = datetime.now(timezone.utc)
    past_date = today - timedelta(days=days)
    
    # 날짜 포맷 변환 (YYYYMMDD)
    start_date_str = past_date.strftime("%Y%m%d")
    end_date_str = today.strftime("%Y%m%d")
    
    # 최근 N일 필터링 쿼리 적용
    query = f"report_date:[{start_date_str} TO {end_date_str}]"
    params = _get_auth_params({"search": query, "limit": limit})
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(OPENFDA_RECALL_URL, params=params)
            response.raise_for_status()
            data = response.json()
            return data.get("results", [])
        except httpx.HTTPStatusError as e:
            # FDA API는 검색 결과가 0건일 때 404를 반환하므로, 이를 에러가 아닌 빈 리스트로 부드럽게 처리
            if e.response.status_code == 404:
                print(f"[Collector] 최근 {days}일간 발생한 Recall 데이터가 없습니다.")
            else:
                print(f"[Collector Error] Recall 데이터 수집 실패: {e}")
            return []
        except Exception as e:
            print(f"[Collector Error] 알 수 없는 오류 발생: {e}")
            return []


# 2. openFDA에서 shortage 이벤트를 비동기로 수집한다.
# Args: limit(최대 이벤트 수)
# Returns: shortage 이벤트 목록 (list[dict])
async def fetch_shortage_events(limit: int = 10) -> list[dict]:
    params = _get_auth_params({"limit": limit})
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(OPENFDA_SHORTAGE_URL, params=params)
            response.raise_for_status()
            data = response.json()
            return data.get("results", [])
        except httpx.HTTPError as e:
            print(f"[Collector Error] Shortage 데이터 수집 실패: {e}")
            return []


# 3. openFDA에서 label update 이벤트를 비동기로 수집한다.
async def fetch_label_events(limit: int = 10) -> list[dict]:
    params = _get_auth_params({"limit": limit})
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(OPENFDA_LABEL_URL, params=params)
            response.raise_for_status()
            data = response.json()
            return data.get("results", [])
        except httpx.HTTPError as e:
            print(f"[Collector Error] Label 데이터 수집 실패: {e}")
            return []


# 로컬 샘플 JSON 파일에서 이벤트 목록을 로드한다. (MVP 테스트용)
def load_sample_events() -> list[dict]:
    if not SAMPLE_DATA_PATH.exists():
        raise FileNotFoundError(
            f"Sample data not found at {SAMPLE_DATA_PATH}. "
            "Please add recall_samples.json under data/event/."
        )

    with open(SAMPLE_DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# 외부 데이터 자동 수집 메인 파이프라인 (주기적 실행용)
async def periodic_collect():
    print("[Collector] 수동 openFDA 데이터 수집 시작...")
    
    recalls = await fetch_recall_events()
    shortages = await fetch_shortage_events()
    labels = await fetch_label_events()
    
    print(f"[Collector] 수집 완료: Recall {len(recalls)}건, Shortage {len(shortages)}건, Label {len(labels)}건")
    
    return {
        "recalls": recalls,
        "shortages": shortages,
        "labels": labels
    }

# --- 테스트 코드 ---
if __name__ == "__main__":
    import asyncio

    async def test_main():
        # 수집기 파이프라인 호출
        result = await periodic_collect()
        
        # 결과 출력 확인
        print("\n=== [테스트] 수집 데이터 확인 ===")
        print(f"Recall 첫 번째 샘플 데이터: {result['recalls'][:1]}")
        print(f"Shortage 첫 번째 샘플 데이터: {result['shortages'][:1]}")
        print(f"Label 첫 번째 샘플 데이터: {result['labels'][:1]}")

    # 비동기 함수 실행
    asyncio.run(test_main())