from __future__ import annotations

from app.rag.filters import FilterCandidate, MetadataFilterBuilder
from app.rag.models import EvidenceChunk, EvidencePlan, EvidenceTarget, RetrievalContext
from app.rag.reranker import MetadataAwareReranker
from app.rag.retriever import MilvusCandidateRetriever
from app.rag.router import EvidenceRouter
from app.rag.service import RetrievalService
from app.rag.set_builder import EvidenceSetBuilder
from app.rag.sufficiency import SufficiencyChecker


class FakeEmbedder:
    def embed(self, query: str) -> list[float]:
        return [0.1, 0.2, 0.3]


class FakeRetriever:
    def __init__(self, chunks: list[EvidenceChunk]) -> None:
        self.chunks = chunks
        self.calls: list[dict[str, object]] = []
        self.last_filter_attempts = [
            {
                "target_document_type": "recall_notice",
                "level": "strong_identifier_section",
                "expr": 'document_type == "recall_notice"',
                "hit_count": 1,
                "stopped_on_hits": True,
            }
        ]

    def retrieve(
        self,
        *,
        query_embedding: list[float],
        context: RetrievalContext,
        plan: EvidencePlan,
        top_k: int,
        filter_override: str | None = None,
    ) -> list[EvidenceChunk]:
        self.calls.append(
            {
                "query_embedding": query_embedding,
                "context": context,
                "plan": plan,
                "top_k": top_k,
                "filter_override": filter_override,
            }
        )
        return self.chunks


class FakeMilvusRetriever(MilvusCandidateRetriever):
    def __init__(self, hits: list[dict]) -> None:
        self.hits = hits
        self.oversample = 4
        self.last_filter_attempts = []

    def _search(self, *, query_embedding: list[float], filter_expr: str, limit: int) -> list[dict]:
        return self.hits


def chunk(**overrides: object) -> EvidenceChunk:
    defaults = {
        "chunk_id": "chunk-1",
        "chunk_index": 0,
        "content": "body",
        "document_id": "doc-1",
        "document_type": "recall_notice",
        "event_type": "recall",
        "section": "recall_notice",
        "source_path": "source.md",
        "score": 0.7,
        "content_hash": "hash-1",
    }
    defaults.update(overrides)
    return EvidenceChunk(**defaults)


def test_evidence_router_builds_recall_required_plan() -> None:
    plan = EvidenceRouter().build_plan(RetrievalContext(event_type="recall"))

    assert plan.required_document_types == ["recall_notice", "policy", "sop"]


def test_metadata_filter_builder_produces_fallback_levels() -> None:
    levels = MetadataFilterBuilder().build_filter_levels(
        RetrievalContext(event_type="label_update", rxnorm_rxcui="74169"),
        EvidenceTarget("label", sections=["warnings", "contraindications"]),
    )

    assert levels[0].level == "strong_identifier_section"
    assert 'rxnorm_rxcui == "74169"' in levels[0].expr
    assert 'section == "warnings"' in levels[0].expr
    assert levels[1].expr == (
        'document_type == "label" and ARRAY_CONTAINS(event_types, "label_update") and rxnorm_rxcui == "74169"'
    )
    assert levels[1].level == "strong_identifier"
    assert 'section == "warnings"' in levels[2].expr
    assert levels[-1].expr == 'document_type == "label" and ARRAY_CONTAINS(event_types, "label_update")'


def test_metadata_filter_builder_scopes_every_level_by_event_type() -> None:
    levels = MetadataFilterBuilder().build_filter_levels(
        RetrievalContext(event_type="shortage"),
        EvidenceTarget("policy", sections=["evidence_requirements"]),
    )

    assert all('ARRAY_CONTAINS(event_types, "shortage")' in level.expr for level in levels)


def test_metadata_filter_builder_skips_event_type_clause_when_unknown() -> None:
    levels = MetadataFilterBuilder().build_filter_levels(
        RetrievalContext(),
        EvidenceTarget("policy"),
    )

    assert levels == [FilterCandidate('document_type == "policy"', "document_type")]


def test_metadata_filter_builder_escapes_filter_string_literals() -> None:
    levels = MetadataFilterBuilder().build_filter_levels(
        RetrievalContext(
            event_type='recall") or document_type != "recall_notice',
            recall_number='D-1" or recall_number != "D-1',
        ),
        EvidenceTarget("recall_notice", sections=['recall_notice\\urgent"']),
    )
    escaped_base = (
        'document_type == "recall_notice" '
        'and ARRAY_CONTAINS(event_types, "recall\\") or document_type != \\"recall_notice")'
    )

    assert levels[0].expr == (
        f'{escaped_base} and recall_number == "D-1\\" or recall_number != \\"D-1" '
        'and section == "recall_notice\\\\urgent\\""'
    )
    assert levels[1].expr == (
        f'{escaped_base} and recall_number == "D-1\\" or recall_number != \\"D-1"'
    )
    assert levels[2].expr == f'{escaped_base} and section == "recall_notice\\\\urgent\\""'


def test_metadata_aware_reranker_promotes_identifier_matches() -> None:
    context = RetrievalContext(event_type="recall", recall_number="D-1", ndc=["123"], lot="LOT-A")
    plan = EvidencePlan(event_type="recall", targets=[EvidenceTarget("recall_notice", sections=["recall_notice"])])
    chunks = [
        chunk(chunk_id="weak", score=0.8, recall_number="D-2", ndc=[], lot=None),
        chunk(chunk_id="strong", score=0.7, recall_number="D-1", ndc=["123"], lot="LOT-A"),
    ]

    reranked = MetadataAwareReranker().rerank(chunks, context=context, plan=plan)

    assert reranked[0].chunk_id == "strong"
    assert "recall_number_match" in reranked[0].rank_reasons
    assert "ndc_match" in reranked[0].rank_reasons
    assert "lot_match" in reranked[0].rank_reasons


def test_sufficiency_checker_reports_missing_required_document_type() -> None:
    plan = EvidencePlan(event_type="recall", targets=[EvidenceTarget("recall_notice"), EvidenceTarget("policy")])

    result = SufficiencyChecker().check([chunk(document_type="recall_notice")], plan=plan)

    assert result.evidence_status == "insufficient"
    assert result.missing_document_types == ["policy"]
    assert result.needs_evidence_review is True


def test_sufficiency_checker_flags_document_type_only_fallback_as_weak() -> None:
    plan = EvidencePlan(event_type="recall", targets=[EvidenceTarget("recall_notice"), EvidenceTarget("policy")])
    chunks = [
        chunk(
            document_type="recall_notice",
            filter_level="strong_identifier",
            matched_identifiers={"recall_number": "D-1"},
        ),
        chunk(chunk_id="policy", document_type="policy", filter_level="document_type"),
    ]

    result = SufficiencyChecker().check(chunks, plan=plan)

    assert result.missing_document_types == []
    assert result.weak_document_types == ["policy"]
    assert result.evidence_status == "insufficient"
    assert result.needs_evidence_review is True


def test_evidence_set_builder_keeps_every_required_type_beyond_top_k() -> None:
    plan = EvidencePlan(
        event_type="recall",
        targets=[EvidenceTarget("recall_notice"), EvidenceTarget("policy"), EvidenceTarget("sop")],
    )
    chunks = [
        chunk(chunk_id="rn", document_type="recall_notice", score=0.9),
        chunk(chunk_id="pol", document_type="policy", score=0.8),
        chunk(chunk_id="sop", document_type="sop", score=0.7),
    ]

    selected = EvidenceSetBuilder().build(chunks, plan=plan, top_k=1)

    assert [item.chunk_id for item in selected] == ["rn", "pol", "sop"]


def test_retrieval_service_orchestrates_retrieval_components() -> None:
    retriever = FakeRetriever(
        [
            chunk(document_type="recall_notice", content_hash="same", score=0.7, recall_number="D-1"),
            chunk(chunk_id="dup", document_type="recall_notice", content_hash="same", score=0.6),
            chunk(chunk_id="policy", document_type="policy", section="evidence_requirements", content_hash="policy", score=0.65),
            chunk(chunk_id="sop", document_type="sop", section="procedure", content_hash="sop", score=0.64),
        ]
    )
    service = RetrievalService(embedder=FakeEmbedder(), candidate_retriever=retriever)

    result = service.retrieve(
        query="what evidence is required?",
        context=RetrievalContext(event_type="recall", recall_number="D-1"),
        top_k=3,
        filter_override='document_type == "recall_notice"',
    )

    assert retriever.calls[0]["filter_override"] == 'document_type == "recall_notice"'
    assert [item.document_type for item in result.chunks] == ["recall_notice", "policy", "sop"]
    assert result.sufficiency.evidence_status == "sufficient"
    assert result.retrieval_trace["counts"] == {
        "candidate_chunks": 4,
        "deduped_chunks": 3,
        "reranked_chunks": 3,
        "selected_chunks": 3,
    }
    assert result.retrieval_trace["filter_attempts"][0]["level"] == "strong_identifier_section"
    assert result.retrieval_trace["selected_chunks"][0]["chunk_id"] == "chunk-1"


def test_milvus_retriever_marks_override_stopped_only_when_hits_exist() -> None:
    retriever = FakeMilvusRetriever(hits=[])

    result = retriever.retrieve(
        query_embedding=[0.1, 0.2, 0.3],
        context=RetrievalContext(),
        plan=EvidencePlan(event_type=None, targets=[]),
        top_k=5,
        filter_override='document_type == "policy"',
    )

    assert result == []
    assert retriever.last_filter_attempts == [
        {
            "target_document_type": "override",
            "level": "override",
            "expr": 'document_type == "policy"',
            "hit_count": 0,
            "stopped_on_hits": False,
        }
    ]
