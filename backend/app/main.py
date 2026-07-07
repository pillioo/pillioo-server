from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
# 추후 스케줄러 복구 시 사용
# from apscheduler.schedulers.asyncio import AsyncIOScheduler

# 중앙 라우터 임포트
from app.api.router import router as api_router

# openFDA 주기적 수집 파이프라인 함수 임포트
# from app.event.collector import periodic_collect


# FastAPI 앱의 시작과 종료 시동을 관리하는 수명주기(lifespan) 정의
@asynccontextmanager
async def lifespan(app: FastAPI):
    # print("⏳ openFDA 자동 수집 스케줄러 가동 준비...")
    # scheduler = AsyncIOScheduler()
    
    # 테스트용: 10초마다 openFDA 데이터 수집 실행
    # (추후 실배포 시에는 hours=24 등으로 간격 조절 가능)
    # scheduler.add_job(periodic_collect, 'interval', seconds=10)
    # scheduler.start()
    # print("✅ 스케줄러 가동 완료! (10초 주기로 백그라운드 수집을 시작합니다)")
    
    # 서버 종료 시 스케줄러도 안전하게 셧다운
    # print("🛑 스케줄러 종료 중...")
    # scheduler.shutdown()

    # openFDA 수집은 현재 /events/collect 수동 트리거로만 실행됩니다.
    yield
    

# lifespan 매니저를 탑재하여 FastAPI 앱 초기화
app = FastAPI(title="P5 Platform MVP", version="0.1.0", lifespan=lifespan)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"], # 추후 프론트엔드 주소로 변경해야 한다.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 예시: health 엔드포인트 (필요 시 활성화 가능)
# 아래 엔드포인트는 예시로 제공된 상태 확인용이며,
# 배포/데모에서 필요 없는 경우 주석 처리하거나 제거해도 무방합니다.
# 만약 사용하려면 활성화해주세요.
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