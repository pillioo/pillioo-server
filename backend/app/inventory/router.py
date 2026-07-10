from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models.ticket import Ticket
from app.inventory.matcher import inventory_match
from app.inventory.impact import assess_impact
from app.inventory.quality import inventory_quality_check

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("/impact/{ticket_id}")
def get_inventory_impact(ticket_id: str, db: Session = Depends(get_db)):
    """
    ticket_id 기준으로 재고 영향도를 조회한다.
    ticket의 drug_name, ndc, lot 정보로 재고 매칭 결과를 반환한다.
    """
    ticket = db.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found")

    drug_name = ticket.drug_name or ""
    ndc = ticket.ndc or ""
    # CodeRabbit 봇 피드백 반영: lot_number -> lot 으로 필드명 수정
    lot = ticket.lot or ""

    match_result = inventory_match(
        drug_name=drug_name,
        ndc=ndc,
        lot=lot,
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