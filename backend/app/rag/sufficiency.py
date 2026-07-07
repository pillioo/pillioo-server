from __future__ import annotations

from app.rag.filters import LOOSE_FILTER_LEVELS
from app.rag.models import EvidenceChunk, EvidencePlan, SufficiencyResult


class SufficiencyChecker:
        def check(self, chunks: list[EvidenceChunk], *, plan: EvidencePlan) -> SufficiencyResult:
            required = plan.required_document_types
            found = sorted({chunk.document_type for chunk in chunks if chunk.document_type in required})
            missing = [document_type for document_type in required if document_type not in found]
            # document_type-only fallback means no relevant section was actually matched.
            types_with_section_evidence = {
                chunk.document_type
                for chunk in chunks
                if chunk.document_type in required and chunk.filter_level not in LOOSE_FILTER_LEVELS
            }
            weak = sorted(set(found) - types_with_section_evidence)
            coverage_score = len(found) / len(required) if required else 1.0
            citations_ready = bool(chunks) and all(chunk.chunk_id and chunk.source_path and chunk.content for chunk in chunks)
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
            )