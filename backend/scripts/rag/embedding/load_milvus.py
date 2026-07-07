from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from scripts.rag.embedding.config import (
    DEFAULT_EMBEDDED_CHUNKS_PATH,
    EMBEDDING_DIM,
    MILVUS_COLLECTION,
    MILVUS_URI,
)
from scripts.rag.embedding.io import read_jsonl
from scripts.rag.embedding.milvus_mapping import to_milvus_row
from scripts.rag.embedding.milvus_schema import create_evidence_schema, create_index_params
from scripts.rag.embedding.validation import (
    validate_collection_dimension,
    validate_collection_fields,
    validate_positive_int,
)


try:
    from pymilvus import MilvusClient
except ImportError as exc:  # pragma: no cover
    raise ImportError("pymilvus is required to load embedded chunks into Milvus.") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Load embedded evidence chunks into Milvus.")
    parser.add_argument("--input", type=Path, default=DEFAULT_EMBEDDED_CHUNKS_PATH)
    parser.add_argument("--uri", default=MILVUS_URI)
    parser.add_argument("--collection", default=MILVUS_COLLECTION)
    parser.add_argument("--embedding-dim", type=int, default=EMBEDDING_DIM)
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--drop-existing", action="store_true")
    return parser


def ensure_collection(
    client: MilvusClient,
    *,
    collection_name: str,
    embedding_dim: int,
    drop_existing: bool,
) -> None:
    if client.has_collection(collection_name):
        if not drop_existing:
            validate_collection_dimension(client, collection_name=collection_name, embedding_dim=embedding_dim)
            validate_collection_fields(client, collection_name=collection_name)
            return
        client.drop_collection(collection_name)

    schema = create_evidence_schema(client, embedding_dim=embedding_dim)
    index_params = create_index_params(client)
    client.create_collection(collection_name=collection_name, schema=schema, index_params=index_params)


def batched(items: list[dict[str, Any]], batch_size: int) -> list[list[dict[str, Any]]]:
    return [items[index : index + batch_size] for index in range(0, len(items), batch_size)]


def load_milvus(
    input_path: Path,
    *,
    uri: str,
    collection_name: str,
    embedding_dim: int,
    batch_size: int,
    drop_existing: bool,
) -> int:
    validate_positive_int(embedding_dim, name="embedding_dim")
    validate_positive_int(batch_size, name="batch_size")
    records = read_jsonl(input_path)
    client = MilvusClient(uri=uri)
    ensure_collection(
        client,
        collection_name=collection_name,
        embedding_dim=embedding_dim,
        drop_existing=drop_existing,
    )

    total = 0
    for batch in batched(records, batch_size):
        rows = [to_milvus_row(record, embedding_dim=embedding_dim) for record in batch]
        client.upsert(collection_name=collection_name, data=rows)
        total += len(rows)
        print(f"[MILVUS] upserted={total}/{len(records)}", flush=True)

    client.flush(collection_name)
    client.load_collection(collection_name)
    return total


def main() -> None:
    args = build_parser().parse_args()
    count = load_milvus(
        args.input,
        uri=args.uri,
        collection_name=args.collection,
        embedding_dim=args.embedding_dim,
        batch_size=args.batch_size,
        drop_existing=args.drop_existing,
    )

    print("[SUMMARY]")
    print(f"input={args.input}")
    print(f"uri={args.uri}")
    print(f"collection={args.collection}")
    print(f"loaded_chunks={count}")


if __name__ == "__main__":
    main()
