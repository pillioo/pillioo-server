from fastapi import APIRouter

router = APIRouter()

# 예시
@router.get("/health")
async def health():
    return {
        "status": "ok",
        "timestamp": "2026-06-17T10:00:00",
        "services": {
            "postgresql": "ok",
            "milvus": "ok"
        }
    }
