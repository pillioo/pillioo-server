from __future__ import annotations

from datetime import datetime, timezone

from app.db.models.report_version_model import ReportVersion
from app.event.safety import draft_safety_check
from app.report.versioning import freeze_final_version, save_report_version
from app.schemas.common import ReportVersionTag
from app.schemas.report import AffectedProduct, DraftReport, EvidenceSummary, InventoryImpact


class FakeSession:
    def __init__(self) -> None:
        self.objects: list = []
        self._next_id = 1

    def add(self, obj) -> None:
        self.objects.append(obj)

    def flush(self) -> None:
        for obj in self.objects:
            if getattr(obj, "id", None) is None:
                obj.id = self._next_id
                self._next_id += 1
            if getattr(obj, "created_at", None) is None:
                obj.created_at = datetime.now(timezone.utc)

    def refresh(self, obj) -> None:
        pass


def make_report(**overrides) -> DraftReport:
    defaults = dict(
        title="Midazolam recall review draft",
        summary="Midazolam class I recall notice.",
        affected_product=AffectedProduct(drug_name="midazolam", ndc="00641601441", lot="LOT-A"),
        inventory_impact=InventoryImpact(matched=True, affected_departments=["ICU"], total_quantity=5),
        evidence_summary=EvidenceSummary(coverage_score=0.9, found_sources=["sop"]),
        recommended_review_action="Pharmacist review required before further action.",
    )
    defaults.update(overrides)
    return DraftReport(**defaults)


def test_save_report_version_persists_structured_report_json_and_created_by() -> None:
    db = FakeSession()
    report = make_report()

    version = save_report_version(
        db=db,
        ticket_id=1,
        version_tag=ReportVersionTag.DRAFT_V1,
        report=report,
        created_by="workflow",
    )

    assert isinstance(version, ReportVersion)
    # created_by was accepted by save_report_version before but silently
    # dropped -- this is the fix for that.
    assert version.created_by == "workflow"
    assert version.report_json is not None
    assert version.report_json["title"] == "Midazolam recall review draft"
    assert version.report_json["affected_product"]["drug_name"] == "midazolam"
    # report_text must still be populated (derived) for plain-text consumers.
    assert version.report_text == report.to_display_text()
    assert "Midazolam class I recall notice." in version.report_text


def test_save_report_version_content_only_path_leaves_report_json_none() -> None:
    """Backward-compat path: callers that only have plain text (e.g. the
    pharmacist-edited draft_v2 path) must still work without report_json."""
    db = FakeSession()

    version = save_report_version(
        db=db,
        ticket_id=1,
        version_tag=ReportVersionTag.DRAFT_V2,
        content="Pharmacist-edited text.",
        created_by="pharm-1",
    )

    assert version.report_text == "Pharmacist-edited text."
    assert version.report_json is None


def test_save_report_version_stores_draft_v2_revision_metadata() -> None:
    db = FakeSession()
    safety_result = draft_safety_check("This is a safe sentence.")

    version = save_report_version(
        db=db,
        ticket_id=1,
        version_tag=ReportVersionTag.DRAFT_V2,
        content="edited text",
        created_by="pharm-1",
        change_summary="Pharmacist edited the draft directly.",
        change_reason="typo fix",
        reviewer_comment="please fix the typo in paragraph 2",
        safety_check_result=safety_result,
    )

    assert version.change_summary == "Pharmacist edited the draft directly."
    assert version.change_reason == "typo fix"
    assert version.reviewer_comment == "please fix the typo in paragraph 2"
    assert version.safety_check_result["needs_action_review"] is False


def test_freeze_final_version_copies_source_without_regenerating() -> None:
    db = FakeSession()
    report = make_report(summary="Approved content, verbatim.")
    source = ReportVersion(
        id=5,
        ticket_id=1,
        version_tag=ReportVersionTag.DRAFT_V2.value,
        report_text=report.to_display_text(),
        report_json=report.model_dump(mode="json"),
    )

    final_version = freeze_final_version(
        db=db,
        ticket_id=1,
        source_version=source,
        approved_by="pharm-1",
        approval_comment="Looks good.",
    )

    # Frozen content must be byte-identical to the source -- no regeneration.
    assert final_version.version_tag == ReportVersionTag.FINAL_V1.value
    assert final_version.report_text == source.report_text
    assert final_version.report_json == source.report_json
    assert final_version.approved_by == "pharm-1"
    assert final_version.approval_comment == "Looks good."
    assert final_version.source_version == ReportVersionTag.DRAFT_V2.value
    assert final_version.approved_at is not None
    assert final_version.created_by == "pharm-1"
