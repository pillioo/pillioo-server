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
    MILVUS_COLLECTION: str = "evidence_chunks"  # pharmaops -> evidence_chunks
    OPENAI_API_KEY: Optional[str] = None
    # Optional OpenAI-compatible gateway base URL for chat/completion calls
    # (draft generation, evidence chat). Leave unset to call api.openai.com
    # directly. Embeddings always call the OpenAI API directly regardless of
    # this setting (see app/core/llm_client.py: embedding_client_kwargs()
    # pins base_url explicitly so the OpenAI SDK's own OPENAI_BASE_URL
    # env-var fallback can't reroute embedding calls through this gateway).
    OPENAI_BASE_URL: Optional[str] = None
    # API key used for embeddings specifically. Needed whenever OPENAI_API_KEY
    # has been repurposed as a gateway key (OPENAI_BASE_URL set to something
    # other than api.openai.com) -- embeddings need a real OpenAI key of
    # their own. Falls back to OPENAI_API_KEY if unset (fine when no gateway
    # is in use and OPENAI_API_KEY is already a real OpenAI key).
    EMBEDDING_API_KEY: Optional[str] = None
    EMBEDDING_MODEL: str = "text-embedding-3-small"  # OPENAI_EMBEDDING_MODEL -> EMBEDDING_MODEL
    EMBEDDING_DIM: int = 1536
    EMBEDDING_BATCH_SIZE: int = 64
    EMBEDDING_PROVIDER: str = "openai"

    # LLM (draft generation, evidence chat)
    LLM_MODEL: str = "gpt-4o-mini"

    class Config:
        env_file = ".env"
        env_prefix = ""
        extra = "ignore"  # ignore remaining .env keys not modeled above (e.g. EMBEDDING_PROVIDER)

settings = Settings()
