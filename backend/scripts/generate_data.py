from __future__ import annotations

import argparse
import subprocess
import sys

DATASET_COMMANDS = {
    "identity": ["scripts.rag.identity.build_drug_identity_cache"],
    "labels": ["scripts.rag.openfda.fetch_labels", "--clean"],
    "recalls": ["scripts.rag.openfda.fetch_recalls", "--clean"],
    "sop": ["scripts.rag.sop.generate_sop_documents"],
    "policy": ["scripts.rag.policy.generate_policy_documents"],
    "chunks": ["scripts.rag.chunking.build_chunks", "--clean"],
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate RAG evidence documents.")
    parser.add_argument("--all", action="store_true", help="Generate all datasets.")
    parser.add_argument("--identity", action="store_true", help="Build RxNorm drug identity cache.")
    parser.add_argument("--labels", action="store_true", help="Generate openFDA label documents.")
    parser.add_argument("--recalls", action="store_true", help="Generate openFDA recall notice documents.")
    parser.add_argument("--sop", action="store_true", help="Generate SOP documents.")
    parser.add_argument("--policy", action="store_true", help="Generate policy documents.")
    parser.add_argument("--chunks", action="store_true", help="Generate chunked evidence JSONL.")
    return parser


def selected_datasets(args: argparse.Namespace) -> list[str]:
    selected = [
        name
        for name in DATASET_COMMANDS
        if args.all or getattr(args, name)
    ]
    return selected or list(DATASET_COMMANDS)


def run_dataset(name: str) -> None:
    module, *module_args = DATASET_COMMANDS[name]
    command = [sys.executable, "-m", module, *module_args]
    print(f"\n[RUN] {' '.join(command)}", flush=True)
    subprocess.run(command, check=True)


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    for dataset in selected_datasets(args):
        run_dataset(dataset)


if __name__ == "__main__":
    main()
