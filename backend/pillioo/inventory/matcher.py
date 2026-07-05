import os
import pandas as pd
from rapidfuzz import fuzz

def inventory_match(drug_name: str, ndc: str, lot: str) -> dict:
    """
    P1에서 정규화된 약물 정보를 바탕으로 병원 재고(CSV)와 매칭합니다.
    """
    try:
        # 현재 스크립트(matcher.py)의 위치를 찾고, 그 안의 mock_data 폴더를 연결
        current_dir = os.path.dirname(os.path.abspath(__file__))
        csv_path = os.path.join(current_dir, "mock_data", "inventory.csv")
        
        df = pd.read_csv(csv_path)
    except FileNotFoundError:
        return {"error": f"{csv_path} 파일을 찾을 수 없습니다."}

    # 결측치(NaN) 처리 (비교할 때 에러 방지)
    df['ndc'] = df['ndc'].fillna('')
    df['drug_name'] = df['drug_name'].fillna('')
    df['lot'] = df['lot'].fillna('')

    # ==========================================
    # 1순위: NDC Exact Match (정확히 일치)
    # ==========================================
    # CSV의 숫자형 NDC(예: 641601441)와 P1의 문자열 NDC(예: "00641601441")를 안전하게 비교하기 위한 내부 검사 함수
    def is_ndc_match(csv_ndc, target_ndc):
        if csv_ndc == '':
            return False
        try:
            # 실수가 섞여 있을 수 있으니 float -> int -> str 변환 후 11자리 0 채우기
            normalized_csv_ndc = str(int(float(csv_ndc))).zfill(11)
            return normalized_csv_ndc == target_ndc
        except ValueError:
            # 변환이 안 되는 문자열이라면 그대로 비교
            return str(csv_ndc).strip() == target_ndc

    exact_df = df[df['ndc'].apply(lambda x: is_ndc_match(x, ndc))]
    
    if not exact_df.empty:
        # Lot 번호 일치 여부 확인 (하나라도 일치하면 True)
        lot_matched = (exact_df['lot'].astype(str) == str(lot)).any()
        
        return {
            "matched": True,
            "match_type": "exact_ndc_match",
            "match_confidence": 1.0, 
            "needs_identity_review": False, 
            "matched_rows": exact_df.to_dict(orient='records')
        }

    # ==========================================
    # 2순위: Fuzzy Drug Name Match (유사도 검사)
    # ==========================================
    df['fuzz_score'] = df['drug_name'].apply(
        lambda x: fuzz.ratio(str(x).lower(), str(drug_name).lower())
    )
    
    # 유사도 85점(0.85) 이상인 행만 필터링
    fuzzy_df = df[df['fuzz_score'] >= 85]
    
    if not fuzzy_df.empty:
        max_score = fuzzy_df['fuzz_score'].max()
        base_confidence = max_score / 100.0
        
        # 보너스: Lot 번호 일치 여부 (최대 1.0)
        lot_matched = (fuzzy_df['lot'].astype(str) == str(lot)).any()
        final_confidence = min(base_confidence + 0.1, 1.0) if lot_matched else base_confidence

        result_df = fuzzy_df.drop(columns=['fuzz_score'])

        return {
            "matched": True,
            "match_type": "fuzzy_name_match",
            "match_confidence": round(final_confidence, 2),
            "needs_identity_review": True, 
            "identity_review_reason": f"NDC mismatch but generic name similar (score: {round(max_score)}%)",
            "matched_rows": result_df.to_dict(orient='records')
        }

    # ==========================================
    # 3순위: No Match (매칭 실패)
    # ==========================================
    return {
        "matched": False,
        "match_type": "no_match",
        "match_confidence": 0.0,
        "needs_identity_review": False,
        "matched_rows": []
    }


# --- 개발자용 로컬 테스트 코드 ---
if __name__ == "__main__":
    import json
    
    print("=== 테스트 1: Exact Match (NDC 일치) ===")
    test_1 = inventory_match(drug_name="midazolam", ndc="00641601441", lot="LOT-A")
    print(json.dumps(test_1, indent=2, ensure_ascii=False))
    
    print("\n=== 테스트 2: Fuzzy Match (이름 유사도) ===")
    test_2 = inventory_match(drug_name="mepivacaine hydrochloride", ndc="99999999999", lot="LOT-D")
    print(json.dumps(test_2, indent=2, ensure_ascii=False))