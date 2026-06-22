from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import ReportVersionTag


class ReportVersion(BaseModel):
    version_id: str
    report_id: str
    ticket_id: str
    version_tag: ReportVersionTag
    content: str
    created_by: str
    created_at: datetime