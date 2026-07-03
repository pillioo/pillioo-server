from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[3]
RAG_DIR = ROOT_DIR / "data" / "rag"
PROCESSED_DIR = RAG_DIR / "processed"

DEFAULT_CHUNKS_PATH = PROCESSED_DIR / "evidence_chunks.jsonl"
DEFAULT_EMBEDDED_CHUNKS_PATH = PROCESSED_DIR / "embedded_chunks.jsonl"

load_dotenv(ROOT_DIR / ".env")

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM") or os.getenv("EMBEDDING_DIMENSION", "1536"))
EMBEDDING_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "64"))

MILVUS_URI = os.getenv("MILVUS_URI", "http://localhost:19530")
MILVUS_COLLECTION = os.getenv("MILVUS_COLLECTION", "evidence_chunks")
