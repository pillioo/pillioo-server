import pandas as pd
import json
from typing import Dict, Any

from app.schemas.common import Department, Priority

# matcher.py의 결과를 받아 병동별 영향도, 우선순위, 긴급도를 평가한다.

def assess_impact(match_result: Dict[str, Any]) -> Dict[str, Any]:

    #1. 매칭된 데이터 추출 및 초기화
    matched_rows = match_result.get("matched_rows", [])
    
    #2. 매칭 결과가 없을 경우 기본값 반환
    if not match_result.get("matched", False) or not matched_rows:
        return {
            "affected_departments": [],
            "department_breakdown": {},
            "total_quantity": 0,
            "priority": Priority.MEDIUM.value,
            "urgent": False,
            "urgent_reason": "No matched inventory found."
        }
    
    #3. 분석을 위한 DataFrame 변환
    df = pd.DataFrame(matched_rows)
    df["department"] = df["department"].apply(
        lambda dept: dept.value if isinstance(dept, Department) else str(dept).strip()
        )
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0)
    
    #4. 병동(department)별 수량 집계
    breakdown_df = df.groupby("department")["quantity"].sum()
    department_breakdown = breakdown_df.to_dict()
    
    affected_departments = sorted(list(department_breakdown.keys()))
    total_quantity = int(df["quantity"].sum())
    
    #5. Priority(우선순위) 결정: ICU/ER 포함 여부 (Enum 사용)
    high_priority_depts = [Department.ICU.value, Department.ER.value]
    priority = Priority.HIGH.value if any(dept in affected_departments for dept in high_priority_depts) else Priority.MEDIUM.value
    
    #6. Urgent(긴급도) 판단: days_remaining이 3 이하인 경우
    urgent = False
    urgent_reason = ""
    
    if "days_remaining" in df.columns:
        df["days_remaining"] = pd.to_numeric(df["days_remaining"], errors="coerce")
        urgent_rows = df[df["days_remaining"] <= 3]
        
        if not urgent_rows.empty:
            urgent = True
            # 가장 긴급한(값이 작은) 행의 정보를 추출
            min_row = urgent_rows.loc[urgent_rows["days_remaining"].idxmin()]
            urgent_reason = f"{min_row['department']} inventory days_remaining: {int(min_row['days_remaining'])}"
    
    # 최종 결과 반환
    return {
        "affected_departments": affected_departments,
        "department_breakdown": department_breakdown,
        "total_quantity": total_quantity,
        "priority": priority,
        "urgent": urgent,
        "urgent_reason": urgent_reason
    }

# --- 개발자용 로컬 테스트 실행 코드 ---
if __name__ == "__main__":
    # 테스트 케이스: ICU 재고가 2일 남음 (HIGH + URGENT 예상)
    test_data = {
        "matched": True,
        "matched_rows": [
            {"department": "ICU", "quantity": 10, "days_remaining": 2},
            {"department": "GW", "quantity": 20, "days_remaining": 5}
        ]
    }
    
    print("=== [테스트] Impact Assessment 결과 ===")
    result = assess_impact(test_data)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    # 간단한 검증
    assert result["priority"] == Priority.HIGH.value
    assert result["urgent"] is True
    print("\n테스트 통과: priority=HIGH, urgent=True 확인됨!")