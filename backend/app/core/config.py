from typing import Optional
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DB_HOST: str = "postgres"
    DB_PORT: int = 5432
    DB_NAME: str = "pillioo_db"
    DB_USER: str = "user"
    DB_PASSWORD: str
    DATABASE_URL: str

    OPENFDA_API_KEY: Optional[str] = None

    # RAG / Milvus
    MILVUS_URI: str = "http://localhost:19530"
    MILVUS_COLLECTION: str = "evidence_chunks"  # pharmaops → evidence_chunks
    OPENAI_API_KEY: Optional[str] = None
    EMBEDDING_MODEL: str = "text-embedding-3-small"  # OPENAI_EMBEDDING_MODEL → EMBEDDING_MODEL
    EMBEDDING_DIM: int = 1536
    EMBEDDING_BATCH_SIZE: int = 64
    EMBEDDING_PROVIDER: str = "openai"

    class Config:
        env_file = ".env"
        env_prefix = ""
        extra = "ignore"  # 위에서 다루지 않는 .env의 나머지 키(EMBEDDING_PROVIDER 등)는 무시한다.

settings = Settings()