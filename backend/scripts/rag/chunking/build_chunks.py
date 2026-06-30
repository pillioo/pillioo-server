from __future__ import annotations

import argparse
from pathlib import Path

from scripts.rag.chunking.core import (
    DEFAULT_CHUNKS_PATH,
    DEFAULT_MANIFEST_PATH,
    DOCUMENTS_DIR,
    build_chunks,
    clean_outputs,
    write_jsonl,
    write_manifest,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Chunk RAG markdown evidence documents.")
    parser.add_argument("--documents-dir", type=Path, default=DOCUMENTS_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_CHUNKS_PATH)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--clean", action="store_true", help="Remove previous chunk outputs first.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    tmp_output = args.output.with_suffix(f"{args.output.suffix}.tmp")
    tmp_manifest = args.manifest.with_suffix(f"{args.manifest.suffix}.tmp")
    if args.clean:
        clean_outputs(args.output, args.manifest, tmp_output, tmp_manifest)

    chunks, manifest = build_chunks(args.documents_dir)
    write_jsonl(chunks, tmp_output).replace(args.output)
    write_manifest(manifest, tmp_manifest).replace(args.manifest)

    print("[SUMMARY]")
    print(f"documents={manifest['total_documents']}")
    print(f"chunks={manifest['total_chunks']}")
    print(f"chunk_path={args.output}")
    print(f"manifest_path={args.manifest}")
    print(f"warnings={len(manifest['warnings'])}")


if __name__ == "__main__":
    main()
