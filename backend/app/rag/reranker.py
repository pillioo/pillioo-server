from __future__ import annotations

from app.rag.filters import LOOSE_FILTER_LEVELS
from app.rag.models import EvidenceChunk, EvidencePlan, RetrievalContext


class MetadataAwareReranker:
    # score is COSINE similarity (higher = better); boosts/penalties are additive on that scale.
    def rerank(self, chunks: list[EvidenceChunk], *, context: RetrievalContext, plan: EvidencePlan) -> list[EvidenceChunk]:
        required_types = set(plan.required_document_types)
        required_sections = {section for target in plan.targets for section in target.sections}

        reranked: list[EvidenceChunk] = []
        for chunk in chunks:
            score = chunk.score
            reasons: list[str] = []
            matched: dict[str, str | list[str]] = {}

            if chunk.document_type in required_types:
                score += 0.05
                reasons.append("required_document_type")
            if chunk.section in required_sections:
                score += 0.08
                reasons.append("required_section")
            if context.recall_number and chunk.recall_number == context.recall_number:
                score += 0.20
                reasons.append("recall_number_match")
                matched["recall_number"] = context.recall_number
            if context.normalized_drug_name and chunk.normalized_drug_name == context.normalized_drug_name:
                score += 0.12
                reasons.append("normalized_drug_name_match")
                matched["normalized_drug_name"] = context.normalized_drug_name
            if context.rxnorm_rxcui and chunk.rxnorm_rxcui == context.rxnorm_rxcui:
                score += 0.10
                reasons.append("rxnorm_rxcui_match")
                matched["rxnorm_rxcui"] = context.rxnorm_rxcui
            ndc_matches = sorted(set(context.ndc) & set(chunk.ndc))
            if ndc_matches:
                score += 0.15
                reasons.append("ndc_match")
                matched["ndc"] = ndc_matches
            if context.lot and chunk.lot == context.lot:
                score += 0.10
                reasons.append("lot_match")
                matched["lot"] = context.lot
            if chunk.filter_level in LOOSE_FILTER_LEVELS:
                score -= 0.03
                reasons.append("loose_filter")
            if not all([chunk.chunk_id, chunk.source_path, chunk.content]):
                score -= 0.20
                reasons.append("missing_citation_fields")

            chunk.rank_score = score
            chunk.rank_reasons = reasons
            chunk.matched_identifiers = matched
            reranked.append(chunk)

        return sorted(reranked, key=lambda item: item.rank_score, reverse=True)
