from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from pillioo.inventory.matcher import inventory_match
from pillioo.inventory.impact import assess_impact
from pillioo.inventory.quality import inventory_quality_check

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("/impact/{ticket_id}")
def get_inventory_impact(ticket_id: str, db: Session = Depends(get_db)):
    """
    ticket_id 기준으로 재고 영향도를 조회한다.
    P4 review payload에 포함되는 엔드포인트.
    """
    # TODO: ticket_id로 DB에서 이벤트 정보 조회
    # 현재는 mock 데이터로 테스트
    mock_event = {
        "drug_name": "midazolam",
        "ndc": "00641601441",
        "lot": "LOT-A",
    }

    match_result = inventory_match(
        drug_name=mock_event["drug_name"],
        ndc=mock_event["ndc"],
        lot=mock_event["lot"],
    )

    if not match_result.get("matched"):
        return {
            "ticket_id": ticket_id,
            "matched": False,
            "message": "No inventory match found.",
        }

    impact_result = assess_impact(match_result)
    quality_result = inventory_quality_check(match_result, impact_result)

    return {
        "ticket_id": ticket_id,
        "match_result": match_result,
        "impact_result": impact_result,
        "quality_result": quality_result,
    }