from __future__ import annotations

from dataclasses import dataclass

from app.rag.models import EvidenceTarget, RetrievalContext
from scripts.rag.embedding.milvus_fields import MilvusField


@dataclass(frozen=True)
class FilterCandidate:
    expr: str
    level: str


# No section/identifier specificity was found beyond this level.
LOOSE_FILTER_LEVELS = frozenset({"document_type", "unknown"})


class MetadataFilterBuilder:
    def build_filter_levels(self, context: RetrievalContext, target: EvidenceTarget) -> list[FilterCandidate]:
        base = [f"{MilvusField.DOCUMENT_TYPE} == {self._string_literal(target.document_type)}"]
        if context.event_type:
            # event_types (array), not event_type, so cross-cutting docs still match.
            base.append(f"ARRAY_CONTAINS({MilvusField.EVENT_TYPES}, {self._string_literal(context.event_type)})")
        levels: list[FilterCandidate] = []

        # ndc/lot are reranker-only signals, not hard filters here.
        strong = [*base]
        if context.recall_number and target.document_type == "recall_notice":
            strong.append(f"{MilvusField.RECALL_NUMBER} == {self._string_literal(context.recall_number)}")
        elif context.rxnorm_rxcui and target.document_type == "label":
            strong.append(f"{MilvusField.RXNORM_RXCUI} == {self._string_literal(context.rxnorm_rxcui)}")
        elif context.normalized_drug_name and target.document_type in {"label", "recall_notice"}:
            strong.append(f"{MilvusField.NORMALIZED_DRUG_NAME} == {self._string_literal(context.normalized_drug_name)}")
        if len(strong) > len(base):
            levels.append(FilterCandidate(" and ".join(strong), "strong_identifier"))

        section_level = [*base]
        if target.sections:
            section_level.append(self._section_expr(target.sections))
        if len(section_level) > len(base):
            levels.append(FilterCandidate(" and ".join(section_level), "section"))

        levels.append(FilterCandidate(" and ".join(base), "document_type"))
        return self._dedupe_levels(levels)

    def _section_expr(self, sections: list[str]) -> str:
        if len(sections) == 1:
            return f"{MilvusField.SECTION} == {self._string_literal(sections[0])}"
        return "(" + " or ".join(f"{MilvusField.SECTION} == {self._string_literal(section)}" for section in sections) + ")"

    def _string_literal(self, value: str) -> str:
        escaped = (
            value.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
        )
        return f'"{escaped}"'

    def _dedupe_levels(self, levels: list[FilterCandidate]) -> list[FilterCandidate]:
        seen: set[str] = set()
        result: list[FilterCandidate] = []
        for level in levels:
            if level.expr in seen:
                continue
            seen.add(level.expr)
            result.append(level)
        return result
