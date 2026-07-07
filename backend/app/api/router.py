from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import get_db
from app.event.router import router as event_router

router = APIRouter()

router.include_router(event_router)

@router.get("/health-db")
async def health_db(db: Session = Depends(get_db)):
    # 간단한 쿼리 예시 (테스트용)
    try:
        db.execute(text("SELECT 1"))
        return {"db": "connected"}
    except SQLAlchemyError as e:
        return {"db": "connection_error", "detail": str(e)}
