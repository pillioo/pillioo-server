from typing import Optional
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DB_HOST: str = "postgres"
    DB_PORT: int = 5432
    DB_NAME: str = "pillioo_db"
    DB_USER: str = "user"
    DB_PASSWORD: str
    DATABASE_URL: str

    # 추가된 부분: .env의 API 키를 받을 공간을 마련해준다.
    OPENFDA_API_KEY: Optional[str] = None

    # RAG/Milvus 연동 설정 (evidence retrieval trigger에서 사용)
    MILVUS_URI: str = "http://localhost:19530"
    MILVUS_COLLECTION: str = "evidence_chunks"
    EMBEDDING_MODEL: str = "text-embedding-3-small"

    class Config:
        env_file = ".env"
        env_prefix = ""
        extra = "ignore"  # 위에서 다루지 않는 .env의 나머지 키(EMBEDDING_PROVIDER 등)는 무시한다.

settings = Settings()
