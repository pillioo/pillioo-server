from __future__ import annotations

import pytest

from app.rag.filters import MetadataFilterBuilder
from app.rag.models import EvidenceChunk, EvidencePlan, EvidenceTarget, RetrievalContext, list_values
from app.rag.reranker import MetadataAwareReranker
from app.rag.router import EvidenceRouter
from app.rag.set_builder import EvidenceSetBuilder, dedupe_chunks
from app.rag.sufficiency import SufficiencyChecker
from scripts.rag.embedding.milvus_fields import MilvusField


def make_chunk(**overrides: object) -> EvidenceChunk:
    defaults = {
        "chunk_id": "chunk-1",
        "chunk_index": 0,
        "content": "body",
        "document_id": "doc-1",
        "document_type": "recall_notice",
        "event_type": "recall",
        "section": "recall_notice",
        "source_path": "data/rag/documents/recall_notice/doc-1.md",
        "score": 0.5,
    }
    defaults.update(overrides)
    return EvidenceChunk(**defaults)



# EvidenceRouter
def test_router_recall_requires_recall_notice_policy_sop() -> None:
    plan = EvidenceRouter().build_plan(RetrievalContext(event_type="recall"), top_k=5)

    assert plan.required_document_types == ["recall_notice", "policy", "sop"]
    assert all(target.required for target in plan.targets)


def test_router_label_update_requires_label_policy_sop() -> None:
    plan = EvidenceRouter().build_plan(RetrievalContext(event_type="label_update"), top_k=5)

    assert plan.required_document_types == ["label", "policy", "sop"]
    assert all(target.required for target in plan.targets)


def test_router_shortage_requires_policy_and_sop_with_label_optional() -> None:
    plan = EvidenceRouter().build_plan(RetrievalContext(event_type="shortage"), top_k=5)

    assert plan.required_document_types == ["policy", "sop"]
    label_target = next(target for target in plan.targets if target.document_type == "label")
    assert label_target.required is False


def test_router_unknown_event_type_does_not_require_all_document_types() -> None:
    plan = EvidenceRouter().build_plan(RetrievalContext(event_type="unknown_thing"), top_k=5)

    assert plan.required_document_types == []
    assert {target.document_type for target in plan.targets} == {
        "recall_notice",
        "label",
        "policy",
        "sop",
    }
    assert all(not target.required for target in plan.targets)



# MetadataFilterBuilder
def test_filter_builder_recall_notice_with_recall_number_creates_strong_identifier() -> None:
    target = EvidenceTarget("recall_notice", sections=["recall_notice"])
    context = RetrievalContext(recall_number="D-0277-2024")

    levels = MetadataFilterBuilder().build_filter_levels(context, target)

    strong = next(level for level in levels if level.level == "strong_identifier")
    assert f'{MilvusField.RECALL_NUMBER} == "D-0277-2024"' in strong.expr


def test_filter_builder_no_recall_number_skips_strong_identifier_for_recall_notice() -> None:
    target = EvidenceTarget("recall_notice", sections=["recall_notice"])
    context = RetrievalContext(recall_number=None)

    levels = MetadataFilterBuilder().build_filter_levels(context, target)

    assert all(level.level != "strong_identifier" for level in levels)


def test_filter_builder_label_with_rxnorm_creates_strong_identifier() -> None:
    target = EvidenceTarget("label", sections=["warnings"])
    context = RetrievalContext(rxnorm_rxcui="74169")

    levels = MetadataFilterBuilder().build_filter_levels(context, target)

    strong = next(level for level in levels if level.level == "strong_identifier")
    assert f'{MilvusField.RXNORM_RXCUI} == "74169"' in strong.expr


def test_filter_builder_normalized_drug_name_is_strong_identifier_fallback() -> None:
    for document_type in ("label", "recall_notice"):
        target = EvidenceTarget(document_type, sections=[])
        context = RetrievalContext(normalized_drug_name="warfarin sodium")

        levels = MetadataFilterBuilder().build_filter_levels(context, target)

        strong = next(level for level in levels if level.level == "strong_identifier")
        assert f'{MilvusField.NORMALIZED_DRUG_NAME} == "warfarin sodium"' in strong.expr


def test_filter_builder_target_sections_create_section_filter() -> None:
    target = EvidenceTarget("policy", sections=["escalation_criteria"])
    context = RetrievalContext()

    levels = MetadataFilterBuilder().build_filter_levels(context, target)

    section_level = next(level for level in levels if level.level == "section")
    assert f'{MilvusField.SECTION} == "escalation_criteria"' in section_level.expr


def test_filter_builder_document_type_fallback_is_always_present() -> None:
    target = EvidenceTarget("sop", sections=[])
    context = RetrievalContext()

    levels = MetadataFilterBuilder().build_filter_levels(context, target)

    assert levels[-1].level == "document_type"
    assert f'{MilvusField.DOCUMENT_TYPE} == "sop"' in levels[-1].expr


def test_filter_builder_escapes_double_quotes_in_values() -> None:
    target = EvidenceTarget("recall_notice", sections=[])
    context = RetrievalContext(recall_number='D-123"quote')

    levels = MetadataFilterBuilder().build_filter_levels(context, target)

    strong = next(level for level in levels if level.level == "strong_identifier")
    assert '\\"quote' in strong.expr
    assert 'D-123"quote' not in strong.expr


def test_filter_builder_escapes_backslashes_in_values() -> None:
    target = EvidenceTarget("label", sections=[])
    context = RetrievalContext(rxnorm_rxcui="74169\\ext")

    levels = MetadataFilterBuilder().build_filter_levels(context, target)

    strong = next(level for level in levels if level.level == "strong_identifier")
    assert "74169\\\\ext" in strong.expr



# MetadataAwareReranker
def test_reranker_boosts_required_document_type_and_section() -> None:
    plan = EvidencePlan(
        event_type="recall",
        targets=[EvidenceTarget("recall_notice", sections=["recall_notice"])],
    )
    context = RetrievalContext()
    chunk = make_chunk(document_type="recall_notice", section="recall_notice", score=0.5)

    [reranked] = MetadataAwareReranker().rerank([chunk], context=context, plan=plan)

    assert reranked.rank_score == pytest.approx(0.5 + 0.05 + 0.08)
    assert "required_document_type" in reranked.rank_reasons
    assert "required_section" in reranked.rank_reasons


def test_reranker_boosts_identifier_matches_and_records_matched_identifiers() -> None:
    plan = EvidencePlan(event_type="recall", targets=[])
    context = RetrievalContext(
        recall_number="D-1",
        rxnorm_rxcui="74169",
        ndc=["00641601441"],
        lot="LOT-A",
    )
    chunk = make_chunk(
        score=0.0,
        recall_number="D-1",
        rxnorm_rxcui="74169",
        ndc=["00641601441"],
        lot="LOT-A",
    )

    [reranked] = MetadataAwareReranker().rerank([chunk], context=context, plan=plan)

    assert reranked.rank_score == pytest.approx(0.20 + 0.10 + 0.15 + 0.10)
    assert set(reranked.rank_reasons) == {
        "recall_number_match",
        "rxnorm_rxcui_match",
        "ndc_match",
        "lot_match",
    }
    assert reranked.matched_identifiers["recall_number"] == "D-1"
    assert reranked.matched_identifiers["ndc"] == ["00641601441"]


def test_reranker_adds_rank_reasons_for_plain_match() -> None:
    plan = EvidencePlan(event_type="recall", targets=[])
    context = RetrievalContext()
    chunk = make_chunk(score=0.5)

    [reranked] = MetadataAwareReranker().rerank([chunk], context=context, plan=plan)

    assert reranked.rank_score == pytest.approx(0.5)
    assert reranked.rank_reasons == []
    assert reranked.matched_identifiers == {}


def test_reranker_penalizes_loose_document_type_only_filter() -> None:
    plan = EvidencePlan(event_type="recall", targets=[])
    context = RetrievalContext()
    chunk = make_chunk(score=0.5, filter_level="document_type")

    [reranked] = MetadataAwareReranker().rerank([chunk], context=context, plan=plan)

    assert reranked.rank_score == pytest.approx(0.5 - 0.03)
    assert "loose_filter" in reranked.rank_reasons


def test_reranker_penalizes_missing_citation_fields() -> None:
    plan = EvidencePlan(event_type="recall", targets=[])
    context = RetrievalContext()
    chunk = make_chunk(score=0.5, source_path="")

    [reranked] = MetadataAwareReranker().rerank([chunk], context=context, plan=plan)

    assert reranked.rank_score == pytest.approx(0.5 - 0.20)
    assert "missing_citation_fields" in reranked.rank_reasons


def test_reranker_sorts_by_rank_score_descending() -> None:
    plan = EvidencePlan(event_type="recall", targets=[])
    context = RetrievalContext()
    low = make_chunk(chunk_id="low", score=0.1)
    high = make_chunk(chunk_id="high", score=0.9)

    result = MetadataAwareReranker().rerank([low, high], context=context, plan=plan)

    assert [chunk.chunk_id for chunk in result] == ["high", "low"]



# EvidenceSetBuilder
def test_set_builder_preserves_required_document_type_coverage_before_filling_top_k() -> None:
    plan = EvidencePlan(
        event_type="recall",
        targets=[
            EvidenceTarget("recall_notice"),
            EvidenceTarget("policy"),
            EvidenceTarget("sop"),
        ],
    )
    chunks = [
        make_chunk(chunk_id="policy-1", document_type="policy", score=0.9),
        make_chunk(chunk_id="policy-2", document_type="policy", score=0.85),
        make_chunk(chunk_id="recall-1", document_type="recall_notice", score=0.5),
        make_chunk(chunk_id="sop-1", document_type="sop", score=0.4),
    ]

    selected = EvidenceSetBuilder().build(chunks, plan=plan, top_k=2)

    selected_ids = [chunk.chunk_id for chunk in selected]
    assert {chunk.document_type for chunk in selected} == {"recall_notice", "policy", "sop"}
    assert "recall-1" in selected_ids
    assert "sop-1" in selected_ids


def test_set_builder_top_k_is_a_floor_not_a_cap_when_required_coverage_exceeds_it() -> None:
    plan = EvidencePlan(
        event_type="recall",
        targets=[
            EvidenceTarget("recall_notice"),
            EvidenceTarget("policy"),
            EvidenceTarget("sop"),
        ],
    )
    chunks = [
        make_chunk(chunk_id="recall-1", document_type="recall_notice", score=0.9),
        make_chunk(chunk_id="policy-1", document_type="policy", score=0.8),
        make_chunk(chunk_id="sop-1", document_type="sop", score=0.7),
    ]

    selected = EvidenceSetBuilder().build(chunks, plan=plan, top_k=1)

    assert len(selected) == 3


def test_dedupe_chunks_keeps_first_chunk_for_repeated_content_hash() -> None:
    chunks = [
        make_chunk(chunk_id="a", content_hash="same"),
        make_chunk(chunk_id="b", content_hash="same"),
        make_chunk(chunk_id="c", content_hash="other"),
        make_chunk(chunk_id="d", content_hash=None),
    ]

    deduped = dedupe_chunks(chunks)

    assert [chunk.chunk_id for chunk in deduped] == ["a", "c", "d"]



# SufficiencyChecker
def test_sufficiency_checker_returns_sufficient_when_required_types_found_non_weak_and_citation_ready() -> None:
    plan = EvidencePlan(
        event_type="recall",
        targets=[
            EvidenceTarget("recall_notice", sections=["recall_notice"]),
            EvidenceTarget("policy", sections=["required_actions"]),
        ],
    )
    chunks = [
        make_chunk(document_type="recall_notice", filter_level="section"),
        make_chunk(document_type="policy", filter_level="strong_identifier"),
    ]

    result = SufficiencyChecker().check(chunks, plan=plan)

    assert result.evidence_status == "sufficient"
    assert result.needs_evidence_review is False
    assert result.citations_ready is True
    assert result.coverage_score == 1.0


def test_sufficiency_checker_insufficient_when_required_document_type_missing() -> None:
    plan = EvidencePlan(
        event_type="recall",
        targets=[
            EvidenceTarget("recall_notice"),
            EvidenceTarget("policy"),
            EvidenceTarget("sop"),
        ],
    )
    chunks = [make_chunk(document_type="recall_notice", filter_level="section")]

    result = SufficiencyChecker().check(chunks, plan=plan)

    assert result.evidence_status == "insufficient"
    assert result.missing_document_types == ["policy", "sop"]
    assert result.needs_evidence_review is True


def test_sufficiency_checker_marks_document_type_only_fallback_as_weak() -> None:
    plan = EvidencePlan(
        event_type="recall",
        targets=[EvidenceTarget("policy", sections=["required_actions"])],
    )
    chunks = [make_chunk(document_type="policy", filter_level="document_type")]

    result = SufficiencyChecker().check(chunks, plan=plan)

    assert result.weak_document_types == ["policy"]
    assert result.evidence_status == "insufficient"


def test_sufficiency_checker_citations_not_ready_when_required_fields_missing() -> None:
    plan = EvidencePlan(event_type="recall", targets=[EvidenceTarget("policy")])
    chunks = [make_chunk(document_type="policy", filter_level="section", source_path="")]

    result = SufficiencyChecker().check(chunks, plan=plan)

    assert result.citations_ready is False
    assert result.evidence_status == "insufficient"


def test_sufficiency_checker_computes_partial_coverage_score() -> None:
    plan = EvidencePlan(
        event_type="recall",
        targets=[
            EvidenceTarget("recall_notice"),
            EvidenceTarget("policy"),
            EvidenceTarget("sop"),
            EvidenceTarget("label"),
        ],
    )
    chunks = [
        make_chunk(document_type="recall_notice", filter_level="section"),
        make_chunk(document_type="policy", filter_level="section"),
    ]

    result = SufficiencyChecker().check(chunks, plan=plan)

    assert result.coverage_score == 0.5


# list_values / EvidenceChunk.from_hit
class FakeRepeatedScalarContainer:
    # Stands in for pymilvus's iterable-but-not-list search() array result.
    def __init__(self, values: list[str]) -> None:
        self._values = values

    def __iter__(self):
        return iter(self._values)

    def __repr__(self) -> str:
        return repr(self._values)


def test_list_values_unwraps_non_list_iterable_like_pymilvus_search_result() -> None:
    container = FakeRepeatedScalarContainer(["52565-009-50"])

    assert list_values(container) == ["52565-009-50"]


def test_list_values_treats_string_as_a_single_scalar_not_characters() -> None:
    assert list_values("52565-009-50") == ["52565-009-50"]


def test_evidence_chunk_from_hit_parses_ndc_from_non_list_iterable() -> None:
    chunk = EvidenceChunk.from_hit(
        {
            "chunk_id": "chunk-1",
            "chunk_index": 0,
            "content": "body",
            "document_id": "doc-1",
            "document_type": "recall_notice",
            "event_type": "recall",
            "section": "recall_notice",
            "source_path": "recall.md",
            "score": 0.5,
            "ndc": FakeRepeatedScalarContainer(["52565-009-50"]),
        }
    )

    assert chunk.ndc == ["52565-009-50"]
