from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models.ticket import Ticket
from app.inventory.matcher import inventory_match
from app.inventory.impact import assess_impact
from app.inventory.quality import inventory_quality_check
from app.schemas.inventory import InventoryImpactResponse

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("/impact/{ticket_id}", response_model=InventoryImpactResponse)
def get_inventory_impact(ticket_id: str, db: Session = Depends(get_db)):
    """
    ticket_id 기준으로 재고 영향도를 조회한다.
    matched 여부와 상관없이 항상 동일한 shape(match_result / impact_result /
    quality_result)로 응답한다.
    """
    ticket = db.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found")

    drug_name = ticket.drug_name or ""
    ndc = ticket.ndc or ""
    lot = ticket.lot or ""

    match_result = inventory_match(drug_name=drug_name, ndc=ndc, lot=lot)

    # matched 여부 상관없이 항상 세 함수 다 호출 -> 응답 shape 고정
    impact_result = assess_impact(match_result)
    quality_result = inventory_quality_check(match_result, impact_result)

    no_match_reason = None
    if not match_result.get("matched"):
        no_match_reason = (
            f"No inventory record found for drug_name={drug_name!r}, "
            f"ndc={ndc!r}, lot={lot!r}."
        )

    return InventoryImpactResponse(
        ticket_id=ticket_id,
        match_result=match_result,
        impact_result=impact_result,
        quality_result=quality_result,
        no_match_reason=no_match_reason,
    )