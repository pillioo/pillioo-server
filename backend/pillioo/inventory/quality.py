from typing import Any, Dict, List

from app.schemas.common import MatchType, Priority


def inventory_quality_check(
    match_result: Dict[str, Any],
    impact_result: Dict[str, Any],
) -> Dict[str, Any]:
    """
    matcher.py와 impact.py 결과를 받아
    Orchestrator Policy Aggregator가 분기 결정에 사용할
    confidence, flags, review_required를 반환한다.
    """

    flags: List[str] = []

    # 1. NDC exact match 여부
    match_type = match_result.get("match_type", "")
    is_exact = match_type == MatchType.EXACT_NDC_MATCH.value
    confidence = 1.0 if is_exact else match_result.get("match_confidence", 0.0)

    # 2. lot 일치 여부 확인
    matched_rows = match_result.get("matched_rows", [])
    lot_matched = any(row.get("lot") for row in matched_rows)
    if lot_matched:
        flags.append("lot_matched")
        confidence = min(confidence + 0.05, 1.0)

    # 3. 수량 존재 여부
    total_quantity = impact_result.get("total_quantity", 0)
    if total_quantity == 0:
        flags.append("no_stock")

    # 4. ICU/ER 포함 여부
    priority = impact_result.get("priority", "")
    if priority == Priority.HIGH.value:
        flags.append("high_priority")

    # 5. identity_review 필요 여부
    needs_identity_review = match_result.get("needs_identity_review", False)
    if needs_identity_review:
        flags.append("identity_uncertain")

    # 6. review_required 결정 (confidence 0.5 미만이면 review 필요)
    review_required = confidence < 0.5 or needs_identity_review

    return {
        "confidence": round(confidence, 2),
        "flags": flags,
        "review_required": review_required,
    }


# --- 개발자용 로컬 테스트 ---
if __name__ == "__main__":
    import json

    match = {
        "matched": True,
        "match_type": "exact_ndc_match",
        "match_confidence": 1.0,
        "needs_identity_review": False,
        "matched_rows": [{"lot": "LOT-A", "quantity": 30, "department": "ICU", "days_remaining": 5}],
    }
    impact = {
        "affected_departments": ["ICU", "ER"],
        "total_quantity": 57,
        "priority": "HIGH",
        "urgent": True,
    }

    result = inventory_quality_check(match, impact)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("\n예상: confidence=1.05→1.0, flags=['lot_matched','high_priority'], review_required=False")