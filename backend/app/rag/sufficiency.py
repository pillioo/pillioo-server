from __future__ import annotations

from app.rag.filters import LOOSE_FILTER_LEVELS
from app.rag.models import EvidenceChunk, EvidencePlan, EvidenceTarget, SufficiencyResult


class SufficiencyChecker:
    def check(self, chunks: list[EvidenceChunk], *, plan: EvidencePlan) -> SufficiencyResult:
        required_targets = {target.document_type: target for target in plan.targets if target.required}
        required = list(required_targets)
        found = sorted({chunk.document_type for chunk in chunks if chunk.document_type in required_targets})
        missing = [document_type for document_type in required if document_type not in found]
        # Evidence is strong only when it proves the required document type at the
        # required section level. A drug/recall identifier match on the wrong label
        # or policy section is still weak for citation-ready drafting.
        types_with_strong_evidence = {
            chunk.document_type
            for chunk in chunks
            if chunk.document_type in required_targets
            and self._is_strong_enough_for_target(chunk, required_targets[chunk.document_type])
        }
        weak = sorted(set(found) - types_with_strong_evidence)
        coverage_score = len(found) / len(required) if required else 1.0
        citations_ready = bool(chunks) and all(chunk.chunk_id and chunk.source_path and chunk.content for chunk in chunks)
        failure_reasons = [
            self._missing_document_type_reason(document_type)
            for document_type in missing
        ]
        failure_reasons.extend(
            self._weak_document_type_reasons(
                document_type=document_type,
                target=required_targets[document_type],
                chunks=[chunk for chunk in chunks if chunk.document_type == document_type],
            )
            for document_type in weak
        )
        if not citations_ready:
            failure_reasons.append(self._citation_not_ready_reason(chunks))
        evidence_status = "sufficient" if not missing and not weak and citations_ready else "insufficient"
        return SufficiencyResult(
            required_document_types=required,
            found_document_types=found,
            missing_document_types=missing,
            weak_document_types=weak,
            coverage_score=round(coverage_score, 4),
            evidence_status=evidence_status,
            needs_evidence_review=evidence_status == "insufficient",
            citations_ready=citations_ready,
            failure_reasons=failure_reasons,
        )

    def _is_strong_enough_for_target(self, chunk: EvidenceChunk, target: EvidenceTarget) -> bool:
        if target.sections:
            return chunk.section in target.sections
        return chunk.filter_level not in LOOSE_FILTER_LEVELS

    def _missing_document_type_reason(self, document_type: str) -> dict[str, object]:
        return {
            "reason": "missing_required_document_type",
            "document_type": document_type,
        }

    def _weak_document_type_reasons(
        self,
        *,
        document_type: str,
        target: EvidenceTarget,
        chunks: list[EvidenceChunk],
    ) -> dict[str, object]:
        if all(chunk.filter_level in LOOSE_FILTER_LEVELS for chunk in chunks):
            return {
                "reason": "only_loose_filter_matched",
                "document_type": document_type,
                "filter_levels": sorted({chunk.filter_level for chunk in chunks}),
            }

        if target.sections:
            matched_sections = sorted({chunk.section for chunk in chunks if chunk.section})
            if any(chunk.filter_level == "strong_identifier" for chunk in chunks):
                return {
                    "reason": "identifier_section_mismatch",
                    "document_type": document_type,
                    "required_sections": target.sections,
                    "matched_sections": matched_sections,
                }
            return {
                "reason": "missing_required_section",
                "document_type": document_type,
                "required_sections": target.sections,
                "matched_sections": matched_sections,
            }

        return {
            "reason": "only_weak_evidence_matched",
            "document_type": document_type,
            "filter_levels": sorted({chunk.filter_level for chunk in chunks}),
        }

    def _citation_not_ready_reason(self, chunks: list[EvidenceChunk]) -> dict[str, object]:
        missing_chunks = [
            {
                "chunk_id": chunk.chunk_id,
                "missing_fields": [
                    field
                    for field, value in {
                        "chunk_id": chunk.chunk_id,
                        "source_path": chunk.source_path,
                        "content": chunk.content,
                    }.items()
                    if not value
                ],
            }
            for chunk in chunks
            if not (chunk.chunk_id and chunk.source_path and chunk.content)
        ]
        return {
            "reason": "citation_not_ready",
            "missing_chunks": missing_chunks,
        }
