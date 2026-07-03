"""
P4 - Report Versioning

Manages report versions throughout the approval workflow.

Version flow:
    draft_v1  → created by Orchestrator after draft generation
    draft_v2  → created after pharmacist revision request
    final_v1  → created after pharmacist approval
"""

from sqlalchemy.orm import Session

from app.db.models.report_version_model import ReportVersion as ReportVersionModel
from app.schemas.common import ReportVersionTag


def save_report_version(
    db: Session,
    ticket_id: str,
    version_tag: ReportVersionTag,
    content: str,
    created_by: str,
) -> ReportVersionModel:
    """
    보고서 버전을 report_versions 테이블에 저장.

    Args:
        db: DB 세션
        ticket_id: 티켓 ID
        version_tag: 버전 태그 (draft_v1 / draft_v2 / final_v1)
        content: 보고서 내용
        created_by: 생성 주체 ("workflow" / 약사 ID)

    Returns:
        ReportVersionModel: 저장된 버전 레코드

    예시:
        # Orchestrator가 초안 생성 후 호출
        save_report_version(db, "T-001", ReportVersionTag.DRAFT_V1, "초안 내용...", "workflow")

        # 약사 수정 후 호출
        save_report_version(db, "T-001", ReportVersionTag.DRAFT_V2, "수정본 내용...", "pharmacist_01")

        # 약사 승인 후 호출
        save_report_version(db, "T-001", ReportVersionTag.FINAL_V1, "최종본 내용...", "pharmacist_01")
    """
    version = ReportVersionModel(
        ticket_id=ticket_id,
        version_tag=version_tag.value,
        content=content,
        created_by=created_by,
    )
    db.add(version)
    db.flush() 
    db.refresh(version)
    return version


def get_report_versions(db: Session, ticket_id: str) -> list[ReportVersionModel]:
    """
    특정 티켓의 모든 보고서 버전 목록 조회.

    GET /reports/{ticket_id}/versions 에서 호출.

    Args:
        db: DB 세션
        ticket_id: 조회할 티켓 ID

    Returns:
        list[ReportVersionModel]: 버전 목록 (생성 시간순)
    """
    return (
        db.query(ReportVersionModel)
        .filter(ReportVersionModel.ticket_id == ticket_id)
        .order_by(ReportVersionModel.created_at.asc())
        .all()
    )


def get_latest_report(db: Session, ticket_id: str) -> ReportVersionModel | None:
    """
    특정 티켓의 가장 최신 보고서 버전 조회.

    GET /reports/{ticket_id} 에서 호출.

    Args:
        db: DB 세션
        ticket_id: 조회할 티켓 ID

    Returns:
        ReportVersionModel | None: 최신 버전 또는 None
    """
    return (
        db.query(ReportVersionModel)
        .filter(ReportVersionModel.ticket_id == ticket_id)
        .order_by(ReportVersionModel.created_at.desc())
        .first()
    )
