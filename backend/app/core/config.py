from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DB_HOST: str = "postgres"
    DB_PORT: int = 5432
    DB_NAME: str = "pillioo_db"
    DB_USER: str = "user"
    DB_PASSWORD: str
    DATABASE_URL: str

    class Config:
        env_file = ".env"
        env_prefix = "" 
        extra = "ignore"  # Ignore RAG/Milvus settings in .env because they are not used here.

settings = Settings()
