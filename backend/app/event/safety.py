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
# 정확한 표현 + 변형 표현 모두 포함
UNSAFE_PATTERNS: dict[BlockedCategory, list[str]] = {
    BlockedCategory.DIRECT_MEDICAL_INSTRUCTION: [
        # 투여 중단
        "즉시 투여",
        "투여를 중단",
        "투여 중단",
        "투여를 멈추",
        "투여를 중지",
        "투여 중지",
        "투여를 금지",
        "투여 금지",
        # 복용 중단
        "복용 중지",
        "복용을 중지",
        "복용을 중단",
        "복용 중단",
        "복용을 멈추",
        "복용을 금지",
        # 사용 중단
        "사용 중단",
        "사용을 중단",
        "사용을 멈추",
        "사용을 중지",
        "사용 중지",
        "사용을 금지",
        "사용 금지",
        # 투약 중단
        "투약 중단",
        "투약을 중단",
        "투약을 중지",
        "투약 중지",
        "투약을 멈추",
        # 기타 직접 지시
        "즉각 중단",
        "즉시 중단",
        "중단하세요",
        "중지하세요",
        "멈추세요",
    ],
    BlockedCategory.SUBSTITUTION_RECOMMENDATION: [
        # 교체
        "교체하세요",
        "교체 바랍니다",
        "교체하시기 바랍니다",
        "교체가 필요합니다",
        "으로 교체",
        "로 교체",
        "교체해 주세요",
        # 대체
        "대체약",
        "대체 약품",
        "대체 약물",
        "대체하세요",
        "대체해 주세요",
        "대체하시기 바랍니다",
        "대신 사용",
        "대신 투여",
        "대신 복용",
        # 변경 - 의료 맥락에 특화된 패턴
        "약으로 변경",
        "약물로 변경",
        "제품으로 변경",
        "제제로 변경",
        "변경하세요",
        "변경 바랍니다",
        "변경해 주세요",
        "변경하시기 바랍니다",
        # 전환 - 의료 맥락에 특화된 패턴
        "약으로 전환",
        "약물로 전환",
        "제품으로 전환",
        "제제로 전환",
        "전환하세요",
        "전환 바랍니다",
    ],
    BlockedCategory.DISPOSAL_INSTRUCTION: [
        # 폐기
        "전량 폐기",
        "폐기하세요",
        "폐기 바랍니다",
        "폐기해 주세요",
        "폐기하시기 바랍니다",
        "폐기가 필요합니다",
        "즉시 폐기",
        "바로 폐기",
        # 버리기
        "버리세요",
        "버려주세요",
        "버리시기 바랍니다",
        "휴지통에 버리",
        "쓰레기통에 버리",
        "폐기물로 처리",
        # 회수
        "회수하세요",
        "즉시 회수",
        "바로 회수",
        "회수 바랍니다",
        "회수해 주세요",
        "회수가 필요합니다",
        # 반납/제거
        "반납하세요",
        "반납 바랍니다",
        "제거하세요",
        "즉시 제거",
        "제거 바랍니다",
        # 소각/파기
        "소각하세요",
        "파기하세요",
        "파기 바랍니다",
    ],
    BlockedCategory.CERTAINTY_WITHOUT_APPROVAL: [
        # 안전 단언
        "안전합니다",
        "안전하니",
        "안전하므로",
        "안전하기 때문에",
        "안전이 확인",
        "안전이 보장",
        # 문제없음 단언
        "문제없습니다",
        "문제 없습니다",
        "문제가 없습니다",
        "이상 없습니다",
        "이상이 없습니다",
        "위험하지 않습니다",
        "위험하지 않으니",
        "위험이 없습니다",
        "위험이 없으니",
        # 계속 사용 권장 - 긍정적 권장 맥락에 특화
        "계속 사용하세요",
        "계속 사용 가능",
        "계속 사용해도 됩니다",
        "계속 사용해도 괜찮",
        "계속 투여하세요",
        "계속 투여 가능",
        "계속 투여해도 됩니다",
        "계속 투여해도 괜찮",
        "계속 복용하세요",
        "계속 복용 가능",
        "계속 복용해도 됩니다",
        "계속 복용해도 괜찮",
        "그대로 사용",
        "그대로 투여",
        "그대로 복용",
        # 효능 단언
        "효과가 있습니다",
        "효능이 있습니다",
        "효과가 보장",
        "효능이 보장",
    ],
}


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
    줄바꿈 기준으로 분리.
    원본 텍스트의 위치 정보를 보존해서 나중에 정확히 교체할 수 있게 함.
    """
    spans = []
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
    """
    blocked_sentences = []
    spans = _find_sentence_spans(draft_text)

    revised_draft = draft_text

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