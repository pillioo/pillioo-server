from __future__ import annotations

from typing import Any, Protocol

from app.rag.filters import MetadataFilterBuilder
from app.rag.models import EvidenceChunk, EvidencePlan, RetrievalContext
from scripts.rag.embedding.milvus_fields import OUTPUT_FIELDS

try:
    from pymilvus import MilvusClient
except ImportError:  # pragma: no cover
    MilvusClient = None  # type: ignore[assignment]


class QueryEmbedder(Protocol):
    def embed(self, query: str) -> list[float]:
        ...


class CandidateRetriever:
    def retrieve(
        self,
        *,
        query_embedding: list[float],
        context: RetrievalContext,
        plan: EvidencePlan,
        top_k: int,
        filter_override: str | None = None,
    ) -> list[EvidenceChunk]:
        raise NotImplementedError


class MilvusCandidateRetriever(CandidateRetriever):
    def __init__(
        self,
        *,
        uri: str,
        collection_name: str,
        filter_builder: MetadataFilterBuilder | None = None,
        nprobe: int = 16,
        oversample: int = 4,
    ) -> None:
        if MilvusClient is None:  # pragma: no cover
            raise ImportError("pymilvus is required to retrieve evidence from Milvus.")
        self.client = MilvusClient(uri=uri)
        self.collection_name = collection_name
        self.filter_builder = filter_builder or MetadataFilterBuilder()
        self.nprobe = nprobe
        self.oversample = oversample

    def retrieve(
        self,
        *,
        query_embedding: list[float],
        context: RetrievalContext,
        plan: EvidencePlan,
        top_k: int,
        filter_override: str | None = None,
    ) -> list[EvidenceChunk]:
        if filter_override:
            # Bypasses the plan entirely, so `top_k` sizes this instead of any target.
            hits = self._search(query_embedding=query_embedding, filter_expr=filter_override, limit=max(top_k, top_k * self.oversample))
            return [
                EvidenceChunk.from_hit(
                    hit,
                    filter_expr=filter_override,
                    filter_level="override",
                    target_document_type=hit.get("document_type"),
                )
                for hit in hits
            ]

        chunks: list[EvidenceChunk] = []
        for target in plan.targets:
            target_limit = max(target.top_k, target.top_k * self.oversample)
            # Levels go strongest-first; stop at the first one with hits instead of mixing levels.
            for candidate in self.filter_builder.build_filter_levels(context, target):
                hits = self._search(query_embedding=query_embedding, filter_expr=candidate.expr, limit=target_limit)
                if hits:
                    chunks.extend(
                        EvidenceChunk.from_hit(
                            hit,
                            filter_expr=candidate.expr,
                            filter_level=candidate.level,
                            target_document_type=target.document_type,
                        )
                        for hit in hits
                    )
                    break
        return chunks

    def _search(self, *, query_embedding: list[float], filter_expr: str, limit: int) -> list[dict[str, Any]]:
        result = self.client.search(
            collection_name=self.collection_name,
            data=[query_embedding],
            filter=filter_expr,
            limit=limit,
            output_fields=OUTPUT_FIELDS,
            search_params={"metric_type": "COSINE", "params": {"nprobe": self.nprobe}},
            anns_field="embedding",
        )
        return [normalize_search_hit(hit) for hit in result[0]]


def normalize_search_hit(hit: dict[str, Any]) -> dict[str, Any]:
    entity = hit.get("entity") or hit
    normalized = dict(entity)
    normalized["score"] = hit.get("distance", hit.get("score"))
    normalized["id"] = hit.get("id", entity.get("chunk_id"))
    return normalized
