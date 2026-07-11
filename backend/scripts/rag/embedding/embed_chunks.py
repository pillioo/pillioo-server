from __future__ import annotations

import argparse
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, TypeVar

from openai import OpenAI

from scripts.rag.embedding.config import (
    DEFAULT_CHUNKS_PATH,
    DEFAULT_EMBEDDED_CHUNKS_PATH,
    EMBEDDING_API_KEY,
    EMBEDDING_BATCH_SIZE,
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    OPENAI_EMBEDDING_BASE_URL,
)
from scripts.rag.embedding.io import append_jsonl, clean_output, read_jsonl
from scripts.rag.embedding.validation import validate_optional_positive_int, validate_positive_int


T = TypeVar("T")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate embeddings for evidence chunks.")
    parser.add_argument("--input", type=Path, default=DEFAULT_CHUNKS_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_EMBEDDED_CHUNKS_PATH)
    parser.add_argument("--model", default=EMBEDDING_MODEL)
    parser.add_argument("--embedding-dim", type=int, default=EMBEDDING_DIM)
    parser.add_argument("--batch-size", type=int, default=EMBEDDING_BATCH_SIZE)
    parser.add_argument("--limit", type=int, default=None, help="Embed only the first N chunks.")
    parser.add_argument("--clean", action="store_true", help="Remove previous embedded output first.")
    return parser


def batched(items: list[T], batch_size: int) -> Iterable[list[T]]:
    for index in range(0, len(items), batch_size):
        yield items[index : index + batch_size]


def embed_texts(client: OpenAI, texts: list[str], model: str) -> list[list[float]]:
    response = client.embeddings.create(model=model, input=texts)
    return [item.embedding for item in response.data]


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def build_embedded_record(
    chunk: dict[str, Any],
    embedding: list[float],
    *,
    model: str,
    embedding_dim: int,
    embedded_at: str,
) -> dict[str, Any]:
    return {
        "chunk_id": chunk["chunk_id"],
        "embedding_model": model,
        "embedding_dim": embedding_dim,
        "embedding_created_at": embedded_at,
        "content_hash": content_hash(str(chunk["content"])),
        "embedding": embedding,
        "content": chunk["content"],
        "document_id": chunk["document_id"],
        "document_type": chunk["document_type"],
        "event_type": chunk["event_type"],
        "event_types": chunk.get("event_types", [chunk["event_type"]]),
        "section": chunk["section"],
        "section_title": chunk["section_title"],
        "title": chunk["title"],
        "source_path": chunk["source_path"],
        "chunk_index": chunk["chunk_index"],
        "token_count": chunk["token_count"],
        "drug_name": chunk.get("drug_name"),
        "normalized_drug_name": chunk.get("normalized_drug_name"),
        "rxnorm_rxcui": chunk.get("rxnorm_rxcui"),
        "classification": chunk.get("classification"),
        "ndc": chunk.get("ndc"),
        "lot": chunk.get("lot"),
        "recall_number": chunk.get("recall_number"),
        "metadata": chunk.get("metadata", {}),
    }


def validate_embedding_dimensions(records: list[dict[str, Any]], embedding_dim: int) -> None:
    invalid = [record["chunk_id"] for record in records if len(record["embedding"]) != embedding_dim]
    if invalid:
        raise ValueError(f"Embedding dimension mismatch for chunks: {invalid[:10]}")


def embed_chunks(
    input_path: Path,
    output_path: Path,
    *,
    model: str,
    embedding_dim: int,
    batch_size: int,
    limit: int | None = None,
) -> int:
    validate_positive_int(embedding_dim, name="embedding_dim")
    validate_positive_int(batch_size, name="batch_size")
    validate_optional_positive_int(limit, name="limit")

    chunks = read_jsonl(input_path)
    if limit is not None:
        chunks = chunks[:limit]

    # Explicit kwargs (not bare OpenAI()) so this never inherits OPENAI_BASE_URL
    # from the environment -- see scripts/rag/embedding/config.py.
    client = OpenAI(api_key=EMBEDDING_API_KEY, base_url=OPENAI_EMBEDDING_BASE_URL)
    total = 0
    for batch in batched(chunks, batch_size):
        embedded_at = datetime.now(timezone.utc).isoformat()
        embeddings = embed_texts(client, [str(chunk["content"]) for chunk in batch], model=model)
        records = [
            build_embedded_record(
                chunk,
                embedding,
                model=model,
                embedding_dim=embedding_dim,
                embedded_at=embedded_at,
            )
            for chunk, embedding in zip(batch, embeddings, strict=True)
        ]
        validate_embedding_dimensions(records, embedding_dim)
        append_jsonl(records, output_path)
        total += len(records)
        print(f"[EMBED] embedded={total}/{len(chunks)}", flush=True)

    return total


def main() -> None:
    args = build_parser().parse_args()
    if args.clean:
        clean_output(args.output)
    elif args.output.exists():
        raise FileExistsError(f"Output already exists. Use --clean to overwrite: {args.output}")

    count = embed_chunks(
        args.input,
        args.output,
        model=args.model,
        embedding_dim=args.embedding_dim,
        batch_size=args.batch_size,
        limit=args.limit,
    )

    print("[SUMMARY]")
    print(f"input={args.input}")
    print(f"output={args.output}")
    print(f"model={args.model}")
    print(f"embedding_dim={args.embedding_dim}")
    print(f"embedded_chunks={count}")


if __name__ == "__main__":
    main()
