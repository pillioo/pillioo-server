from __future__ import annotations

import argparse

from scripts.generate_data import selected_datasets


def make_args(**overrides: bool) -> argparse.Namespace:
    values = {
        "all": False,
        "identity": False,
        "labels": False,
        "recalls": False,
        "sop": False,
        "policy": False,
        "chunks": False,
        "embeddings": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_selected_datasets_includes_chunks_before_embeddings() -> None:
    assert selected_datasets(make_args(embeddings=True)) == ["chunks", "embeddings"]


def test_selected_datasets_does_not_duplicate_chunks() -> None:
    assert selected_datasets(make_args(chunks=True, embeddings=True)) == ["chunks", "embeddings"]
