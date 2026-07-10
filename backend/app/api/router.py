from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import get_db
from app.event.router import router as event_router
from app.orchestration.router import router as orchestration_router
from app.rag.api import router as rag_router
from app.review.router import router as review_router


router = APIRouter()

router.include_router(event_router)

router.include_router(rag_router)
router.include_router(review_router)
router.include_router(orchestration_router)

@router.get("/health-db")
async def health_db(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"db": "connected"}
    except SQLAlchemyError as e:
        return {"db": "connection_error", "detail": str(e)}
