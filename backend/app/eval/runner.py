import json
import asyncio
import httpx
from pathlib import Path
from typing import Any

BASE_URL = "http://localhost:8000"
SCENARIOS_DIR = Path(__file__).parent / "scenarios"


async def run_scenario(scenario: dict) -> dict:
    """시나리오 하나를 실행하고 결과를 반환한다."""
    scenario_id = scenario["scenario_id"]
    input_event = scenario["input_event"]
    expected = scenario["expected"]

    try:
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:

            # 1. 이벤트 업로드
            response = await client.post("/events/upload", json=input_event)
            if response.status_code != 200:
                return {
                    "scenario_id": scenario_id,
                    "passed": False,
                    "error": f"Event upload failed: {response.status_code}",
                }

            ticket_id = response.json().get("ticket_id")
            if not ticket_id:
                return {
                    "scenario_id": scenario_id,
                    "passed": False,
                    "error": "ticket_id not returned from event upload",
                }

            # 2. Workflow 실행
            response = await client.post(f"/tickets/{ticket_id}/run")
            if response.status_code != 200:
                return {
                    "scenario_id": scenario_id,
                    "passed": False,
                    "error": f"Workflow run failed: {response.status_code}",
                }

            # 3. 티켓 상태 조회 (폴링)
            actual = None
            for _ in range(10):
                await asyncio.sleep(1)
                response = await client.get(f"/tickets/{ticket_id}")
                if response.status_code == 200:
                    actual = response.json()
                    if actual.get("status") not in (None, "PROCESSING"):
                        break

            if actual is None:
                return {
                    "scenario_id": scenario_id,
                    "passed": False,
                    "error": "Workflow timeout",
                }

            # 4. 결과 비교
            passed = (
                actual.get("review_type") == expected.get("review_type")
                and actual.get("status") == expected.get("final_status")
            )

            return {
                "scenario_id": scenario_id,
                "passed": passed,
                "expected_review_type": expected.get("review_type"),
                "actual_review_type": actual.get("review_type"),
                "expected_final_status": expected.get("final_status"),
                "actual_final_status": actual.get("status"),
            }

    except httpx.TimeoutException:
        return {
            "scenario_id": scenario_id,
            "passed": False,
            "error": "Request timeout",
        }
    except httpx.RequestError as e:
        return {
            "scenario_id": scenario_id,
            "passed": False,
            "error": f"Network error: {str(e)}",
        }


async def run_all_scenarios() -> list[dict]:
    """scenarios/ 폴더의 모든 시나리오를 실행한다."""
    results = []
    scenario_files = sorted(SCENARIOS_DIR.glob("*.json"))

    for scenario_file in scenario_files:
        with open(scenario_file, encoding="utf-8") as f:
            scenario = json.load(f)
        print(f"Running: {scenario['scenario_id']}...")
        result = await run_scenario(scenario)
        results.append(result)
        status = "PASS" if result.get("passed") else "FAIL"
        print(f"  {status}: {scenario['scenario_id']}")

    return results


if __name__ == "__main__":
    results = asyncio.run(run_all_scenarios())
    passed = sum(1 for r in results if r.get("passed"))
    print(f"\n결과: {passed}/{len(results)} 통과")