from __future__ import annotations

from app.rag.models import EvidenceChunk, EvidencePlan


class EvidenceSetBuilder:
    # Assumes chunks are pre-sorted best-first (post-rerank).
    def build(self, chunks: list[EvidenceChunk], *, plan: EvidencePlan, top_k: int) -> list[EvidenceChunk]:
        selected: list[EvidenceChunk] = []
        selected_ids: set[str] = set()

        for document_type in plan.required_document_types:
            best = next(
                (chunk for chunk in chunks if chunk.document_type == document_type and chunk.chunk_id not in selected_ids),
                None,
            )
            if best is not None:
                selected.append(best)
                selected_ids.add(best.chunk_id)

        # top_k is a floor, not a cap: required coverage above can exceed it.
        fill_limit = max(top_k, len(plan.required_document_types))
        for chunk in chunks:
            if len(selected) >= fill_limit:
                break
            if chunk.chunk_id in selected_ids:
                continue
            selected.append(chunk)
            selected_ids.add(chunk.chunk_id)

        return selected


def dedupe_chunks(chunks: list[EvidenceChunk], *, field: str = "content_hash") -> list[EvidenceChunk]:
    seen: set[str] = set()
    deduped: list[EvidenceChunk] = []
    for chunk in chunks:
        value = getattr(chunk, field, None)
        if value in (None, ""):
            deduped.append(chunk)
            continue
        key = str(value)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(chunk)
    return deduped
