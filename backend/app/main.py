from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from .api.router import router as api_router

app = FastAPI(title="P5 Platform MVP", version="0.1.0")

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"], # 추후 프론트엔드 주소로 변경해야 함
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 예시: health 엔드포인트 (필요 시 활성화 가능)
# 아래 엔드포인트는 예시로 제공된 상태 확인용이며,
# 배포/데모에서 필요 없는 경우 주석 처리하거나 제거해도 무방합니다.
# 만약 사용하려면 활성화해 주세요.
# @app.get("/health")
# async def health():
#     return {
#         "status": "ok",
#         "timestamp": datetime.utcnow().isoformat() + "Z",
#         "services": {
#             "postgresql": "ok",
#             "milvus": "not_checked"  # 필요시 실서비스 체크 로직으로 대체
#         }
#     }

# 예시: 중앙 라우터 연결
app.include_router(api_router)
