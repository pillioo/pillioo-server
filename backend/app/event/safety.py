"""
P1 - Safety Check

Scans report draft sentences for unsafe medical instructions
and replaces them with a safe placeholder.

Called by Orchestrator after draft generation.
Returns SafetyCheckResult with blocked sentences and revised draft.

Language support:
    ko: Korean substring matching
    en: English regex matching (handles morphological variants)
"""

import re

from app.schemas.common import BlockedCategory
from app.schemas.event import BlockedSentence, SafetyCheckResult


REPLACEMENT = "담당 약사 확인 후 조치하세요."

# ──────────────────────────────────────────────
# 한국어 패턴 (substring matching)
# ──────────────────────────────────────────────

KO_UNSAFE_PATTERNS: dict[BlockedCategory, list[str]] = {
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
        # 변경
        "약으로 변경",
        "약물로 변경",
        "제품으로 변경",
        "제제로 변경",
        "변경하세요",
        "변경 바랍니다",
        "변경해 주세요",
        "변경하시기 바랍니다",
        # 전환
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
        # 계속 사용 권장
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

# ──────────────────────────────────────────────
# 영어 패턴 (regex matching — 어미 변화 대응)
# ──────────────────────────────────────────────

EN_UNSAFE_PATTERNS: dict[BlockedCategory, list[str]] = {
    BlockedCategory.DIRECT_MEDICAL_INSTRUCTION: [
        # discontinue variants
        r'\bdiscontinue\b',
        r'\bdiscontinued\b',
        r'\bdiscontinuing\b',
        r'\bdiscontinuation\b',
        # stop/halt/cease administration
        r'\bstop\s+(administration|use|dosing|treatment)\b',
        r'\bhalt\s+(administration|use|dosing)\b',
        r'\bcease\s+(administration|use|dosing)\b',
        # do not administer
        r'\bdo\s+not\s+administer\b',
        r'\bdo\s+not\s+use\b',
        r'\bdo\s+not\s+dispense\b',
        # withhold
        r'\bwithhold\b',
        r'\bimmediately\s+stop\b',
        r'\bimmediately\s+discontinue\b',
    ],
    BlockedCategory.SUBSTITUTION_RECOMMENDATION: [
        # replace/substitute
        r'\breplace\s+with\b',
        r'\bsubstitute\s+with\b',
        r'\bsubstitute\s+for\b',
        r'\bswitch\s+to\b',
        r'\bchange\s+to\b',
        r'\bconvert\s+to\b',
        # use alternative
        r'\buse\s+(an?\s+)?alternative\b',
        r'\balternative\s+medication\b',
        r'\balternative\s+drug\b',
        r'\balternate\s+therapy\b',
    ],
    BlockedCategory.DISPOSAL_INSTRUCTION: [
        # discard/dispose
        r'\bdiscard\b',
        r'\bdispose\s+of\b',
        r'\bdestroy\b',
        r'\brecall\s+and\s+discard\b',
        # return/destroy
        r'\breturn\s+(to|all)\b',
        r'\bremove\s+from\s+(use|stock|circulation)\b',
        r'\bquarantine\s+and\s+destroy\b',
        r'\bimmediately\s+discard\b',
        r'\bimmediately\s+dispose\b',
    ],
    BlockedCategory.CERTAINTY_WITHOUT_APPROVAL: [
        # safe to use
        r'\bsafe\s+to\s+(use|administer|continue)\b',
        r'\bno\s+risk\b',
        r'\bno\s+harm\b',
        r'\bno\s+safety\s+concern\b',
        # continue use
        r'\bcontinue\s+(use|administration|dosing|treatment)\b',
        r'\bmay\s+continue\b',
        r'\bcan\s+continue\b',
        # effective/guaranteed
        r'\bguaranteed\s+(safe|effective)\b',
        r'\bconfirmed\s+safe\b',
        r'\bno\s+action\s+required\b',
    ],
}


# ──────────────────────────────────────────────
# Detection functions
# ──────────────────────────────────────────────

def detect_category(
    sentence: str,
    lang: str = "ko",
) -> BlockedCategory | None:
    """
    문장이 어떤 위험 카테고리에 해당하는지 판단.
    해당 없으면 None 반환.

    Args:
        sentence: 검사할 문장
        lang: 언어 ("ko" 또는 "en")
            - ko: substring matching (한국어 어미 변화 고려)
            - en: regex matching (영어 형태소 변화 대응)

    Returns:
        BlockedCategory | None
    """
    if lang == "ko":
        for category, patterns in KO_UNSAFE_PATTERNS.items():
            for pattern in patterns:
                if pattern in sentence:
                    return category

    elif lang == "en":
        for category, patterns in EN_UNSAFE_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, sentence, re.IGNORECASE):
                    return category

    return None


def scan_evidence_sentence(sentence: str) -> BlockedCategory | None:
    """
    영어 evidence 문서에서 단일 문장을 검사.
    파이프라인 [4]→[5] 지점 (Evidence Retrieval → Sufficiency Check) 에서 호출.

    RAG에서 가져온 영어 문서 청크 안에 unsafe 표현이 있는지 확인.
    있으면 해당 카테고리 반환, 없으면 None.

    Args:
        sentence: 영어 evidence 문서의 단일 문장

    Returns:
        BlockedCategory | None
    """
    return detect_category(sentence, lang="en")


# ──────────────────────────────────────────────
# Draft safety check (Korean draft)
# ──────────────────────────────────────────────

def _find_sentence_spans(text: str) -> list[tuple[int, int]]:
    """
    텍스트에서 문장의 시작/끝 위치(span)를 찾아 반환.
    줄바꿈 기준으로 분리.
    """
    spans = []
    for match in re.finditer(r'[^\n]+', text):
        spans.append((match.start(), match.end()))
    return spans


def draft_safety_check(draft_text: str) -> SafetyCheckResult:
    """
    보고서 초안(한국어)을 문장 단위로 검사해서 위험 문장만 교체.
    위험하지 않은 문장과 원본 줄바꿈/공백은 그대로 보존.

    Orchestrator가 draft 생성 후 이 함수를 호출.

    Args:
        draft_text: LLM이 생성한 보고서 초안 전체 텍스트 (한국어)

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
        category = detect_category(sentence, lang="ko")

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