"""
P4 - Report Versioning

Manages report versions throughout the approval workflow.

Version flow:
    draft_v1  -> created by Orchestrator after draft generation
    draft_v2  -> created after pharmacist revision (edited directly, or
                 system-revised on the pharmacist's behalf)
    final_v1  -> created after pharmacist approval, by freezing the approved
                 draft_v1/draft_v2 as-is (never regenerated)
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models.report_version_model import ReportVersion as ReportVersionModel
from app.schemas.common import ReportVersionTag
from app.schemas.event import SafetyCheckResult
from app.schemas.report import DraftReport


def save_report_version(
    db: Session,
    ticket_id: int,
    version_tag: ReportVersionTag,
    content: str | None = None,
    report: DraftReport | None = None,
    created_by: str | None = None,
    change_summary: str | None = None,
    change_reason: str | None = None,
    reviewer_comment: str | None = None,
    safety_check_result: SafetyCheckResult | None = None,
) -> ReportVersionModel:
    """
    보고서 버전을 report_versions 테이블에 저장.

    Args:
        db: DB 세션
        ticket_id: 티켓 ID
        version_tag: 버전 태그 (draft_v1 / draft_v2 / final_v1)
        content: 평문 보고서 내용. report가 주어지면 무시되고
            report.to_display_text()로 대체된다 (report_text는 항상 평문
            소비자(chat, safety check 등)를 위해 채워진다).
        report: 구조화된 보고서 본문 (DraftReport). 주어지면 report_json에
            저장되고 report_text는 여기서 평문으로 파생된다.
        created_by: 생성 주체 ("workflow" / 약사 ID)
        change_summary: draft_v2일 때 이전 버전 대비 무엇이 바뀌었는지 요약
        change_reason: draft_v2일 때 왜 바뀌었는지
        reviewer_comment: draft_v2를 촉발한 약사 코멘트/수정 요청
        safety_check_result: 수정 후 재실행한 safety check 결과

    Returns:
        ReportVersionModel: 저장된 버전 레코드

    예시:
        # Orchestrator가 초안 생성 후 호출 (구조화된 report 사용)
        save_report_version(db, ticket.id, ReportVersionTag.DRAFT_V1, report=draft_report, created_by="workflow")

        # 약사 수정 후 호출 (평문만 있는 경우도 계속 지원)
        save_report_version(db, ticket.id, ReportVersionTag.DRAFT_V2, content="수정본 내용...", created_by="pharmacist_01")
    """
    if report is not None:
        report_text = report.to_display_text()
        report_json = report.model_dump(mode="json")
    elif content is not None:
        report_text = content
        report_json = None
    else:
        raise ValueError("save_report_version requires either `content` or `report`.")

    version = ReportVersionModel(
        ticket_id=ticket_id,
        version_tag=version_tag.value,
        report_text=report_text,
        report_json=report_json,
        created_by=created_by,
        change_summary=change_summary,
        change_reason=change_reason,
        reviewer_comment=reviewer_comment,
        safety_check_result=safety_check_result.model_dump(mode="json") if safety_check_result else None,
    )
    db.add(version)
    db.flush()
    db.refresh(version)
    return version


def freeze_final_version(
    db: Session,
    ticket_id: int,
    source_version: ReportVersionModel,
    approved_by: str,
    approval_comment: str | None = None,
) -> ReportVersionModel:
    """
    승인된 draft를 그대로 복사해 final_v1으로 저장 (재생성하지 않음).

    최종 승인 단계에서 LLM을 다시 호출하면 약사가 확인하지 않은 문장이
    추가되거나 기존 표현이 달라질 수 있으므로, source_version의
    report_text/report_json을 그대로 freeze하고 승인 메타데이터만 덧붙인다.
    이렇게 해야 약사가 실제로 검토한 문서와 최종 저장된 문서가 일치함을
    보장할 수 있다 (auditability).

    Args:
        db: DB 세션
        ticket_id: 티켓 ID
        source_version: 승인 대상이 된 draft_v1 또는 draft_v2 레코드
        approved_by: 승인한 약사 식별자
        approval_comment: 승인 코멘트

    Returns:
        ReportVersionModel: 저장된 final_v1 레코드
    """
    version = ReportVersionModel(
        ticket_id=ticket_id,
        version_tag=ReportVersionTag.FINAL_V1.value,
        report_text=source_version.report_text,
        report_json=source_version.report_json,
        created_by=approved_by,
        approved_by=approved_by,
        approved_at=datetime.now(timezone.utc),
        approval_comment=approval_comment,
        source_version=source_version.version_tag,
        # Carry forward whatever safety check result the source version had
        # (e.g. from its draft_v2 revision), rather than re-running one.
        safety_check_result=source_version.safety_check_result,
    )
    db.add(version)
    db.flush()
    db.refresh(version)
    return version


def get_report_versions(db: Session, ticket_id: int) -> list[ReportVersionModel]:
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


def get_latest_report(db: Session, ticket_id: int) -> ReportVersionModel | None:
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
