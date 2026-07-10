from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import ReportVersionTag
from app.schemas.event import SafetyCheckResult
from app.schemas.evidence import DraftCitation


class AffectedProduct(BaseModel):
    drug_name: str
    ndc: Optional[str] = None
    lot: Optional[str] = None
    classification: Optional[str] = None


class InventoryImpact(BaseModel):
    matched: bool = False
    affected_departments: list[str] = Field(default_factory=list)
    total_quantity: int = 0
    priority: Optional[str] = None
    # Free-text note for anything about the inventory picture that is not
    # confidently known (e.g. "identity match below confidence threshold").
    uncertainty: Optional[str] = None


class EvidenceSummary(BaseModel):
    coverage_score: float = Field(0.0, ge=0.0, le=1.0)
    found_sources: list[str] = Field(default_factory=list)
    missing_sources: list[str] = Field(default_factory=list)
    key_findings: list[str] = Field(default_factory=list)


class DraftReport(BaseModel):
    """
    Structured report body -- the content of a single report version
    (draft_v1 / draft_v2 / final_v1).

    Versioning and approval metadata (who/when/why a version was created)
    live alongside this in ReportVersion, not inside the report body itself,
    so the same DraftReport shape can be reused unchanged across all three
    version stages.

    Covers the minimum structure agreed for every draft/report: title,
    summary, affected drug/NDC/lot, event classification, affected inventory
    summary, evidence summary, recommended review action, citations,
    pharmacist notes, and safety warnings. version metadata and status
    (draft/final/revised) are carried by ReportVersion instead.
    """

    title: str
    summary: str
    affected_product: AffectedProduct
    event_classification: Optional[str] = None
    inventory_impact: InventoryImpact
    evidence_summary: EvidenceSummary
    recommended_review_action: str
    pharmacist_checklist: list[str] = Field(default_factory=list)
    citations: list[DraftCitation] = Field(default_factory=list)
    pharmacist_notes: list[str] = Field(default_factory=list)
    safety_notes: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    def to_display_text(self) -> str:
        """
        Flatten the structured report into the plain-text form existing
        consumers still rely on: Ticket.draft_text / TicketState.draft_text,
        the chat prompt's ticket state summary, draft_safety_check(), and
        ReportVersion.report_text. Keeping this derivation in one place means
        those call sites don't need to know the report is structured.
        """
        lines: list[str] = [self.title, "", self.summary]

        product_bits = [self.affected_product.drug_name]
        if self.affected_product.ndc:
            product_bits.append(f"NDC {self.affected_product.ndc}")
        if self.affected_product.lot:
            product_bits.append(f"lot {self.affected_product.lot}")
        classification = self.event_classification or self.affected_product.classification
        if classification:
            product_bits.append(classification)
        lines.append("")
        lines.append("Affected product: " + ", ".join(product_bits))

        impact = self.inventory_impact
        impact_bits = [
            f"departments={', '.join(impact.affected_departments) or 'none'}",
            f"quantity={impact.total_quantity}",
        ]
        if impact.priority:
            impact_bits.append(f"priority={impact.priority}")
        if impact.uncertainty:
            impact_bits.append(f"uncertainty={impact.uncertainty}")
        lines.append("Inventory impact: " + ", ".join(impact_bits))

        evidence = self.evidence_summary
        lines.append(
            "Evidence sufficiency: coverage="
            f"{evidence.coverage_score}, missing={', '.join(evidence.missing_sources) or 'none'}"
        )
        if evidence.key_findings:
            lines.append("Key findings: " + "; ".join(evidence.key_findings))

        lines.append("Recommended review action: " + self.recommended_review_action)

        if self.pharmacist_checklist:
            lines.append("Pharmacist checklist: " + "; ".join(self.pharmacist_checklist))
        if self.pharmacist_notes:
            lines.append("Pharmacist notes: " + "; ".join(self.pharmacist_notes))
        if self.safety_notes:
            lines.append("Safety notes: " + "; ".join(self.safety_notes))
        if self.limitations:
            lines.append("Limitations: " + "; ".join(self.limitations))

        return "\n".join(lines)


class ReportVersion(BaseModel):
    """Response shape for a persisted report_versions row."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_id: int
    version_tag: ReportVersionTag
    report_text: str
    report: Optional[DraftReport] = Field(default=None, validation_alias="report_json")
    created_by: Optional[str] = None

    # draft_v2 revision metadata (see DraftReport docstring for why this
    # lives here instead of on the report body).
    change_summary: Optional[str] = None
    change_reason: Optional[str] = None
    reviewer_comment: Optional[str] = None
    safety_check_result: Optional[SafetyCheckResult] = None

    # final_v1 approval metadata.
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    approval_comment: Optional[str] = None
    source_version: Optional[str] = None

    created_at: datetime
    updated_at: Optional[datetime] = None
