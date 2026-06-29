import os
import pandas as pd
from rapidfuzz import fuzz

from app.schemas.common import MatchType 

# P1에서 정규화된 약물 정보를 바탕으로 병원 재고(CSV)와 매칭한다.

def inventory_match(drug_name: str, ndc: str, lot: str) -> dict:

    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        csv_path = os.path.join(current_dir, "mock_data", "inventory.csv")
        df = pd.read_csv(csv_path)
    except FileNotFoundError:
        return {
            "matched": False,
            "match_type": MatchType.NO_MATCH.value,
            "match_confidence": 0.0,
            "needs_identity_review": False,
            "matched_rows": [],
            "error": f"{csv_path} 파일을 찾을 수 없습니다.",
        }

    df['ndc'] = df['ndc'].fillna('')
    df['drug_name'] = df['drug_name'].fillna('')
    df['lot'] = df['lot'].fillna('')

    # ==========================================
    # 1순위: NDC Exact Match (정확히 일치)
    # ==========================================
    def is_ndc_match(csv_ndc, target_ndc):
        if csv_ndc == '':
            return False
        try:
            normalized_csv_ndc = str(int(float(csv_ndc))).zfill(11)
            return normalized_csv_ndc == target_ndc
        except ValueError:
            return str(csv_ndc).strip() == target_ndc

    exact_df = df[df['ndc'].apply(lambda x: is_ndc_match(x, ndc))]
    
    if not exact_df.empty:
        lot_matched = (exact_df['lot'].astype(str) == str(lot)).any()
        return {
            "matched": True,
            "match_type": MatchType.EXACT_NDC_MATCH.value,  # Enum 적용
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
    
    fuzzy_df = df[df['fuzz_score'] >= 85]
    
    if not fuzzy_df.empty:
        max_score = fuzzy_df['fuzz_score'].max()
        base_confidence = max_score / 100.0
        
        lot_matched = (fuzzy_df['lot'].astype(str) == str(lot)).any()
        final_confidence = min(base_confidence + 0.1, 1.0) if lot_matched else base_confidence
        result_df = fuzzy_df.drop(columns=['fuzz_score'])

        return {
            "matched": True,
            "match_type": MatchType.FUZZY_NAME_MATCH.value,  # Enum 적용
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
        "match_type": MatchType.NO_MATCH.value,  # Enum 적용
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