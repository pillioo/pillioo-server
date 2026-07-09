"""
Orchestration trigger endpoint.

Runs the full ticket workflow (inventory match -> evidence retrieval ->
sufficiency check -> draft generation -> safety check -> policy routing)
for a ticket that already exists (e.g. created via /events/upload but
never processed).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.orchestration.service import run_ticket_workflow
from app.rag.service import RetrievalService
from app.review.tickets import get_ticket_by_public_id
from app.schemas.common import Classification, EventType, TicketStatus
from app.schemas.event import EventNormalized
from app.schemas.io import WorkflowRunResponse

router = APIRouter(tags=["orchestration"])


def _event_from_ticket(ticket) -> EventNormalized:
    return EventNormalized(
        event_id=ticket.openfda_id or ticket.recall_number,
        event_type=EventType(ticket.event_type),
        drug_name=ticket.drug_name,
        ndc=ticket.ndc,
        lot=ticket.lot,
        classification=Classification(ticket.classification) if ticket.classification else None,
        status=ticket.source_status or "ongoing",
        recall_number=ticket.recall_number,
        reason_for_recall=ticket.reason_for_recall,
        product_description=ticket.product_description,
    )


@router.post("/tickets/{ticket_id}/run", response_model=WorkflowRunResponse)
async def run_ticket(
    ticket_id: str,
    db: Session = Depends(get_db),
) -> WorkflowRunResponse:
    """
    이미 생성된 티켓에 대해 orchestration 워크플로우를 실행(또는 재실행)한다.
    CREATED/WORKFLOW_FAILED 상태의 티켓만 실제로 처리되고, 이미 처리된 티켓은
    현재 상태를 그대로 반환한다 (중복 실행 방지).
    """
    ticket = get_ticket_by_public_id(db, ticket_id)
    event = _event_from_ticket(ticket)
    evidence_service = RetrievalService.from_milvus(
        uri=settings.MILVUS_URI,
        collection_name=settings.MILVUS_COLLECTION,
        embedding_model=settings.EMBEDDING_MODEL,
    )

    result = run_ticket_workflow(db=db, event=event, evidence_service=evidence_service)

    return WorkflowRunResponse(
        ticket_id=result.ticket.ticket_id,
        status=TicketStatus(result.ticket.status),
    )
