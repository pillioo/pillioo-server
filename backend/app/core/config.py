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

    class Config:
        env_file = ".env"
        env_prefix = "" 
        extra = "ignore"  # Ignore RAG/Milvus settings in .env because they are not used here.

settings = Settings()
