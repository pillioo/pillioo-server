"""
P1 - Safety Check

Scans report draft sentences for unsafe medical instructions
and replaces them with a safe placeholder.

Called by Orchestrator after draft generation.
Returns SafetyCheckResult with blocked sentences and revised draft.
"""

import re

from app.schemas.common import BlockedCategory
from app.schemas.event import BlockedSentence, SafetyCheckResult


REPLACEMENT = "담당 약사 확인 후 조치하세요."

# 카테고리별 위험 키워드 패턴
UNSAFE_PATTERNS: dict[BlockedCategory, list[str]] = {
    BlockedCategory.DIRECT_MEDICAL_INSTRUCTION: [
        "즉시 투여",
        "투여를 중단",
        "투여 중단",
        "복용 중지",
        "복용을 중지",
        "사용 중단",
        "사용을 중단",
        "투약 중단",
        "투약을 중단",
    ],
    BlockedCategory.SUBSTITUTION_RECOMMENDATION: [
        "교체하세요",
        "교체 바랍니다",
        "대체약",
        "대체 약품",
        "대신 사용",
        "으로 변경",
        "로 변경",
        "으로 교체",
        "로 교체",
    ],
    BlockedCategory.DISPOSAL_INSTRUCTION: [
        "전량 폐기",
        "폐기하세요",
        "폐기 바랍니다",
        "버리세요",
        "회수하세요",
        "즉시 회수",
        "반납하세요",
    ],
    BlockedCategory.CERTAINTY_WITHOUT_APPROVAL: [
        "안전합니다",
        "문제없습니다",
        "계속 사용",
        "계속 투여",
        "이상 없습니다",
        "위험하지 않습니다",
    ],
}


def split_sentences(text: str) -> list[str]:
    """
    초안 텍스트를 문장 단위로 분리.

    마침표, 느낌표, 줄바꿈 기준으로 분리.
    예:
        "안녕하세요. 즉시 투여를 중단하세요.\n확인 바랍니다."
        → ["안녕하세요.", "즉시 투여를 중단하세요.", "확인 바랍니다."]
    """
    # 마침표/느낌표/줄바꿈 기준으로 분리
    sentences = re.split(r'(?<=[.!])\s+|\n+', text.strip())
    return [s.strip() for s in sentences if s.strip()]


def detect_category(sentence: str) -> BlockedCategory | None:
    """
    문장이 어떤 위험 카테고리에 해당하는지 판단.
    해당 없으면 None 반환.
    """
    for category, patterns in UNSAFE_PATTERNS.items():
        for pattern in patterns:
            if pattern in sentence:
                return category
    return None


def _find_sentence_spans(text: str) -> list[tuple[int, int]]:
    """
    텍스트에서 문장의 시작/끝 위치(span)를 찾아 반환.
    줄바꿈 또는 마침표/느낌표 뒤 공백을 기준으로 분리.
    원본 텍스트의 위치 정보를 보존해서 나중에 정확히 교체할 수 있게 함.
    """
    spans = []
    # 줄바꿈 또는 마침표/느낌표 뒤 공백 기준으로 분리
    for match in re.finditer(r'[^\n]+', text):
        spans.append((match.start(), match.end()))
    return spans


def draft_safety_check(draft_text: str) -> SafetyCheckResult:
    """
    보고서 초안을 문장 단위로 검사해서 위험 문장만 교체.
    위험하지 않은 문장과 원본 줄바꿈/공백은 그대로 보존.

    Orchestrator가 draft 생성 후 이 함수를 호출.

    Args:
        draft_text: LLM이 생성한 보고서 초안 전체 텍스트

    Returns:
        SafetyCheckResult:
            - blocked_sentences: 차단된 문장 목록 (원문, 카테고리, 대체문)
            - revised_draft: 위험 문장만 교체된 수정 초안 (나머지 포맷 보존)
            - needs_action_review: 차단된 문장이 하나라도 있으면 True

    예시:
        입력:
            "ICU 담당자께 안내드립니다.\n해당 lot은 격리 구역으로 이동하시고,\n즉시 투여를 중단하세요.\n전량 폐기하세요."

        출력:
            blocked_sentences: [
                BlockedSentence(original="즉시 투여를 중단하세요.", ...),
                BlockedSentence(original="전량 폐기하세요.", ...)
            ]
            revised_draft:
                "ICU 담당자께 안내드립니다.\n해당 lot은 격리 구역으로 이동하시고,\n담당 약사 확인 후 조치하세요.\n담당 약사 확인 후 조치하세요."
            needs_action_review: True
    """
    blocked_sentences = []
    spans = _find_sentence_spans(draft_text)

    # 원본 텍스트를 그대로 복사해두고 위험 문장만 교체
    revised_draft = draft_text

    # 뒤에서부터 교체해야 앞 문장의 위치(offset)가 안 밀림
    for start, end in reversed(spans):
        sentence = draft_text[start:end]
        category = detect_category(sentence)

        if category:
            blocked_sentences.insert(
                0,
                BlockedSentence(
                    original=sentence,
                    category=category,
                    replaced_with=REPLACEMENT,
                )
            )
            revised_draft = revised_draft[:start] + REPLACEMENT + revised_draft[end:]

    return SafetyCheckResult(
        blocked_sentences=blocked_sentences,
        revised_draft=revised_draft,
        needs_action_review=len(blocked_sentences) > 0,
    )
