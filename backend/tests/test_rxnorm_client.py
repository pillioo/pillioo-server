from __future__ import annotations

from scripts.rag.identity.rxnorm_client import _normalization_variants


def test_normalization_variants_chain_vehicle_and_combination() -> None:
    variants = _normalization_variants("drug alpha and drug beta in sodium chloride")

    assert ("drug alpha and drug beta", "rxnorm_exact_stripped_vehicle") in variants
    assert ("drug alpha/drug beta", "rxnorm_exact_normalised_combination_stripped_vehicle") in variants


def test_normalization_variants_desalt_chained_combination() -> None:
    variants = _normalization_variants("piperacillin sodium and tazobactam sodium in sodium chloride")

    assert (
        "piperacillin/tazobactam",
        "rxnorm_exact_desalted_combination_stripped_vehicle",
    ) in variants
