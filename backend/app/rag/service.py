from __future__ import annotations

from dataclasses import replace
from typing import Any

from openai import OpenAI

from app.core.llm_client import embedding_client_kwargs
from app.rag.filters import MetadataFilterBuilder
from app.rag.models import EvidenceResult, RetrievalContext
from app.rag.reranker import MetadataAwareReranker
from app.rag.retriever import CandidateRetriever, MilvusCandidateRetriever, QueryEmbedder
from app.rag.router import EvidenceRouter
from app.rag.set_builder import EvidenceSetBuilder, dedupe_chunks
from app.rag.sufficiency import SufficiencyChecker


class OpenAIQueryEmbedder:
    def __init__(self, *, model: str) -> None:
        # Explicit kwargs (not bare OpenAI()) so this never inherits
        # OPENAI_BASE_URL from the environment -- see embedding_client_kwargs().
        self.client = OpenAI(**embedding_client_kwargs())
        self.model = model

    def embed(self, query: str) -> list[float]:
        response = self.client.embeddings.create(model=self.model, input=query)
        return response.data[0].embedding


class RetrievalService:
    def __init__(
        self,
        *,
        embedder: QueryEmbedder,
        candidate_retriever: CandidateRetriever,
        evidence_router: EvidenceRouter | None = None,
        reranker: MetadataAwareReranker | None = None,
        set_builder: EvidenceSetBuilder | None = None,
        sufficiency_checker: SufficiencyChecker | None = None,
    ) -> None:
        self.embedder = embedder
        self.candidate_retriever = candidate_retriever
        self.evidence_router = evidence_router or EvidenceRouter()
        self.reranker = reranker or MetadataAwareReranker()
        self.set_builder = set_builder or EvidenceSetBuilder()
        self.sufficiency_checker = sufficiency_checker or SufficiencyChecker()

    @classmethod
    def from_milvus(
        cls,
        *,
        uri: str,
        collection_name: str,
        embedding_model: str,
        nprobe: int = 16,
        oversample: int = 4,
    ) -> "RetrievalService":
        return cls(
            embedder=OpenAIQueryEmbedder(model=embedding_model),
            candidate_retriever=MilvusCandidateRetriever(
                uri=uri,
                collection_name=collection_name,
                filter_builder=MetadataFilterBuilder(),
                nprobe=nprobe,
                oversample=oversample,
            ),
        )

    def retrieve(
        self,
        *,
        query: str,
        context: RetrievalContext | None = None,
        top_k: int = 5,
        filter_override: str | None = None,
    ) -> EvidenceResult:
        retrieval_context = replace(context or RetrievalContext(), query=query)
        plan = self.evidence_router.build_plan(retrieval_context, top_k=top_k)
        query_embedding = self.embedder.embed(query)
        # top_k here only bounds filter_override/the final set; per-target volume is target.top_k.
        candidates = self.candidate_retriever.retrieve(
            query_embedding=query_embedding,
            context=retrieval_context,
            plan=plan,
            top_k=top_k,
            filter_override=filter_override,
        )
        # Dedupe before rerank so the same content isn't scored twice.
        deduped = dedupe_chunks(candidates)
        reranked = self.reranker.rerank(deduped, context=retrieval_context, plan=plan)
        evidence_set = self.set_builder.build(reranked, plan=plan, top_k=top_k)
        sufficiency = self.sufficiency_checker.check(evidence_set, plan=plan)
        retrieval_trace = build_retrieval_trace(
            plan=plan,
            candidates=candidates,
            deduped=deduped,
            reranked=reranked,
            evidence_set=evidence_set,
            filter_attempts=getattr(self.candidate_retriever, "last_filter_attempts", []),
        )
        return EvidenceResult(
            query=query,
            context=retrieval_context,
            plan=plan,
            chunks=evidence_set,
            sufficiency=sufficiency,
            retrieval_trace=retrieval_trace,
        )


def build_retrieval_trace(
    *,
    plan,
    candidates,
    deduped,
    reranked,
    evidence_set,
    filter_attempts: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "targets": [target.to_dict() for target in plan.targets],
        "filter_attempts": filter_attempts,
        "counts": {
            "candidate_chunks": len(candidates),
            "deduped_chunks": len(deduped),
            "reranked_chunks": len(reranked),
            "selected_chunks": len(evidence_set),
        },
        "selected_chunks": [
            {
                "chunk_id": chunk.chunk_id,
                "document_type": chunk.document_type,
                "section": chunk.section,
                "source_path": chunk.source_path,
                "score": chunk.score,
                "rank_score": chunk.rank_score,
                "rank_reasons": chunk.rank_reasons,
                "matched_identifiers": chunk.matched_identifiers,
                "filter_level": chunk.filter_level,
                "target_document_type": chunk.target_document_type,
            }
            for chunk in evidence_set
        ],
        "filter_levels": sorted({chunk.filter_level for chunk in evidence_set if chunk.filter_level}),
        "rank_reasons": sorted({reason for chunk in evidence_set for reason in chunk.rank_reasons}),
    }
