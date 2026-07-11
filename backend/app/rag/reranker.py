from __future__ import annotations

import re

from app.rag.filters import LOOSE_FILTER_LEVELS
from app.rag.models import EvidenceChunk, EvidencePlan, RetrievalContext


class MetadataAwareReranker:
    # score is COSINE similarity (higher = better); boosts/penalties are additive on that scale.
    LEXICAL_OVERLAP_MAX_BOOST = 0.10
    FALLBACK_IDENTIFIER_MISMATCH_PENALTY = 0.15

    def rerank(self, chunks: list[EvidenceChunk], *, context: RetrievalContext, plan: EvidencePlan) -> list[EvidenceChunk]:
        required_types = set(plan.required_document_types)
        required_sections = {section for target in plan.targets for section in target.sections}

        reranked: list[EvidenceChunk] = []
        for chunk in chunks:
            score = chunk.score
            reasons: list[str] = []
            matched: dict[str, str | list[str]] = {}
            lexical_overlap_score, lexical_overlap_terms = lexical_overlap(context.query, chunk)
            if lexical_overlap_score:
                score += lexical_overlap_score
                reasons.append("lexical_overlap")

            if chunk.document_type in required_types:
                score += 0.05
                reasons.append("required_document_type")
            if chunk.section in required_sections:
                score += 0.08
                reasons.append("required_section")
            if same_identifier(chunk.recall_number, context.recall_number):
                score += 0.20
                reasons.append("recall_number_match")
                matched["recall_number"] = context.recall_number
            if same_identifier(chunk.normalized_drug_name, context.normalized_drug_name):
                score += 0.12
                reasons.append("normalized_drug_name_match")
                matched["normalized_drug_name"] = context.normalized_drug_name
            if same_identifier(chunk.rxnorm_rxcui, context.rxnorm_rxcui):
                score += 0.10
                reasons.append("rxnorm_rxcui_match")
                matched["rxnorm_rxcui"] = context.rxnorm_rxcui
            ndc_matches = sorted(ndc_matches_for(context.ndc, chunk.ndc))
            if ndc_matches:
                score += 0.15
                reasons.append("ndc_match")
                matched["ndc"] = ndc_matches
            if same_identifier(chunk.lot, context.lot):
                score += 0.10
                reasons.append("lot_match")
                matched["lot"] = context.lot
            if should_penalize_identifier_fallback(chunk, context, matched, required_types):
                score -= self.FALLBACK_IDENTIFIER_MISMATCH_PENALTY
                reasons.append("fallback_penalty")
            if chunk.filter_level in LOOSE_FILTER_LEVELS:
                score -= 0.03
                reasons.append("loose_filter")
            if not all([chunk.chunk_id, chunk.source_path, chunk.content]):
                score -= 0.20
                reasons.append("missing_citation_fields")

            chunk.rank_score = score
            chunk.rank_reasons = reasons
            chunk.matched_identifiers = matched
            chunk.lexical_overlap_score = lexical_overlap_score
            chunk.lexical_overlap_terms = lexical_overlap_terms
            reranked.append(chunk)

        return sorted(reranked, key=lambda item: item.rank_score, reverse=True)


def lexical_overlap(query: str, chunk: EvidenceChunk) -> tuple[float, list[str]]:
    query_terms = tokenize(query)
    if not query_terms:
        return 0.0, []

    chunk_terms = tokenize(
        " ".join(
            item
            for item in [
                chunk.content,
                chunk.title or "",
                chunk.section_title or "",
                chunk.source_path,
                chunk.drug_name or "",
                chunk.normalized_drug_name or "",
                chunk.recall_number or "",
                chunk.lot or "",
                chunk.rxnorm_rxcui or "",
                " ".join(chunk.ndc),
            ]
            if item
        )
    )
    overlap_terms = sorted(query_terms & chunk_terms)
    if not overlap_terms:
        return 0.0, []

    overlap_ratio = len(overlap_terms) / len(query_terms)
    score = min(MetadataAwareReranker.LEXICAL_OVERLAP_MAX_BOOST, round(overlap_ratio * 0.10, 4))
    return score, overlap_terms[:20]


def tokenize(value: str) -> set[str]:
    return {
        term
        for term in re.findall(r"[0-9A-Za-z가-힣]+", value.lower())
        if len(term) > 1 and term not in STOPWORDS
    }


def should_penalize_identifier_fallback(
    chunk: EvidenceChunk,
    context: RetrievalContext,
    matched_identifiers: dict[str, str | list[str]],
    required_types: set[str],
) -> bool:
    if chunk.document_type != "recall_notice":
        return False
    if required_types and chunk.document_type not in required_types:
        return False
    if matched_identifiers:
        return False
    if not context_has_strong_identifier(context):
        return False
    if chunk.filter_level in {"strong_identifier", "strong_identifier_section"}:
        return False
    return True


def same_identifier(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    return normalize_identifier(left) == normalize_identifier(right)


def ndc_matches_for(context_ndc: list[str], chunk_ndc: list[str]) -> list[str]:
    chunk_by_normalized = {normalize_ndc(value): value for value in chunk_ndc if normalize_ndc(value)}
    matches: list[str] = []
    for value in context_ndc:
        normalized = normalize_ndc(value)
        if normalized and normalized in chunk_by_normalized:
            matches.append(value)
    return matches


def normalize_identifier(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def normalize_ndc(value: str) -> str:
    return re.sub(r"\D", "", value)


def context_has_strong_identifier(context: RetrievalContext) -> bool:
    return any(
        [
            context.recall_number,
            context.ndc,
            context.lot,
            context.normalized_drug_name,
            context.rxnorm_rxcui,
        ]
    )


STOPWORDS = frozenset(
    {
        "and",
        "or",
        "the",
        "for",
        "with",
        "this",
        "that",
        "what",
        "which",
        "about",
        "evidence",
        "requirements",
        "required",
        "actions",
        "해야",
        "근거",
        "조치",
        "필요",
    }
)
