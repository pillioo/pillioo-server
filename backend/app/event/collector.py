"""
P1 - Event Collector (Skeleton)

Fetches recall and shortage events from openFDA API.

MVP: This module is NOT used in MVP.
     Manual JSON upload via POST /events/upload is used instead.

Future: FastAPI BackgroundTasks로 주기적으로 openFDA API 호출 예정.
"""

import json
from pathlib import Path

# openFDA API 엔드포인트
OPENFDA_RECALL_URL = "https://api.fda.gov/drug/enforcement.json"
OPENFDA_SHORTAGE_URL = "https://api.fda.gov/drug/shortages.json"
OPENFDA_LABEL_URL = "https://api.fda.gov/drug/label.json"

# 샘플 데이터 경로 — __file__ 기준으로 resolve해서 실행 위치 무관하게 동작
SAMPLE_DATA_PATH = Path(__file__).parent.parent.parent.parent / "data" / "event" / "recall_samples.json"


def fetch_recall_events(limit: int = 10) -> list[dict]:
    """
    openFDA에서 recall 이벤트를 가져옴.

    MVP에서는 사용하지 않음.
    샘플 JSON 업로드 방식으로 대체.

    Args:
        limit: 가져올 이벤트 수

    Returns:
        list[dict]: recall 이벤트 목록

    TODO: 2주차 이후 구현
        import httpx
        response = httpx.get(OPENFDA_RECALL_URL, params={"limit": limit})
        return response.json()["results"]
    """
    # TODO: 실제 API 호출로 교체
    pass


def fetch_shortage_events(limit: int = 10) -> list[dict]:
    """
    openFDA에서 shortage 이벤트를 가져옴.

    MVP에서는 사용하지 않음.

    Args:
        limit: 가져올 이벤트 수

    Returns:
        list[dict]: shortage 이벤트 목록

    TODO: 2주차 이후 구현
    """
    # TODO: 실제 API 호출로 교체
    pass


def load_sample_events() -> list[dict]:
    """
    로컬 샘플 JSON 파일에서 이벤트 목록을 불러옴.

    MVP에서 실제 API 대신 사용하는 함수.

    Returns:
        list[dict]: 샘플 recall 이벤트 목록 (42개)

    예시:
        events = load_sample_events()
        for event in events:
            normalized = normalize_event(event)
    """
    if not SAMPLE_DATA_PATH.exists():
        raise FileNotFoundError(
            f"Sample data not found at {SAMPLE_DATA_PATH}. "
            "Please add recall_samples.json under data/event/."
        )

    with open(SAMPLE_DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# TODO: 2주차 이후 - FastAPI BackgroundTasks로 주기적 수집
# async def periodic_collect(background_tasks: BackgroundTasks):
#     background_tasks.add_task(fetch_recall_events)
