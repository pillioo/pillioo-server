from __future__ import annotations

from datetime import datetime, timezone

from app.db.models.approval_model import Approval
from app.db.models.audit_log_model import AuditLog
from app.db.models.report_version_model import ReportVersion
from app.report.versioning import save_report_version
from app.review.approval import handle_approve
from app.schemas.common import ReportVersionTag
from app.schemas.review import ApproveRequest


class FakeSession:
    def __init__(self) -> None:
        self.objects = []
        self.committed = False
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
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(timezone.utc)

    def commit(self) -> None:
        self.committed = True


def test_save_report_version_uses_report_text_and_integer_ticket_fk() -> None:
    db = FakeSession()

    version = save_report_version(
        db=db,
        ticket_id=42,
        version_tag=ReportVersionTag.DRAFT_V1,
        content="Draft body",
        created_by="workflow",
    )

    assert isinstance(version, ReportVersion)
    assert version.ticket_id == 42
    assert version.version_tag == ReportVersionTag.DRAFT_V1.value
    assert version.report_text == "Draft body"


def test_handle_approve_persists_integer_fk_and_returns_public_ticket_id() -> None:
    db = FakeSession()

    result = handle_approve(
        db=db,
        ticket_id=42,
        public_ticket_id="T-PUBLIC",
        request=ApproveRequest(reviewer="pharm-1", comment="ok"),
        current_draft="Final body",
    )

    approval = next(obj for obj in db.objects if isinstance(obj, Approval))
    version = next(obj for obj in db.objects if isinstance(obj, ReportVersion))
    audit = next(obj for obj in db.objects if isinstance(obj, AuditLog))

    assert approval.ticket_id == 42
    assert version.ticket_id == 42
    assert audit.ticket_id == 42
    assert version.report_text == "Final body"
    assert result["ticket_id"] == "T-PUBLIC"
    assert db.committed is True
