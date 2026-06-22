# backend/pillioo/app/db/session.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings  # settings에서 DB 정보를 읽어옴

# 데이터베이스 URL 구성 (PostgreSQL + psycopg2 드라이버)
DATABASE_URL = (
    f"postgresql+psycopg2://{settings.DB_USER}:"
    f"{settings.DB_PASSWORD}@{settings.DB_HOST}:"
    f"{settings.DB_PORT}/{settings.DB_NAME}"
)

# 엔진 생성
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# 세션 팩토리 생성
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 의존성 주입용 제네레이터
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
