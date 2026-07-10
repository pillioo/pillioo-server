"""
Tests for safety check — bilingual (ko + en) unsafe sentence detection.

Run:
    pytest backend/tests/test_safety_check.py -v
"""

import pytest

from app.event.safety import (
    BlockedCategory,
    detect_category,
    draft_safety_check,
    scan_evidence_sentence,
)


# ──────────────────────────────────────────────
# Korean (ko) — detect_category
# ──────────────────────────────────────────────

class TestDetectCategoryKorean:

    def test_direct_medical_instruction_stop(self):
        assert detect_category("투여 중단하세요.", lang="ko") == BlockedCategory.DIRECT_MEDICAL_INSTRUCTION

    def test_direct_medical_instruction_no_take(self):
        assert detect_category("복용하지 마세요.", lang="ko") == BlockedCategory.DIRECT_MEDICAL_INSTRUCTION

    def test_direct_medical_instruction_immediate(self):
        assert detect_category("즉시 투여를 중단하세요.", lang="ko") == BlockedCategory.DIRECT_MEDICAL_INSTRUCTION

    def test_substitution_recommendation_replace(self):
        assert detect_category("대체약으로 변경하세요.", lang="ko") == BlockedCategory.SUBSTITUTION_RECOMMENDATION

    def test_substitution_recommendation_alternative(self):
        assert detect_category("대체약을 사용하세요.", lang="ko") == BlockedCategory.SUBSTITUTION_RECOMMENDATION

    def test_disposal_instruction_discard(self):
        assert detect_category("폐기하세요.", lang="ko") == BlockedCategory.DISPOSAL_INSTRUCTION

    def test_disposal_instruction_recall(self):
        assert detect_category("즉시 회수하세요.", lang="ko") == BlockedCategory.DISPOSAL_INSTRUCTION

    def test_certainty_without_approval_safe(self):
        assert detect_category("이 약은 안전합니다.", lang="ko") == BlockedCategory.CERTAINTY_WITHOUT_APPROVAL

    def test_certainty_without_approval_continue(self):
        assert detect_category("계속 사용하세요.", lang="ko") == BlockedCategory.CERTAINTY_WITHOUT_APPROVAL

    def test_safe_sentence_returns_none(self):
        assert detect_category("해당 lot은 격리 구역으로 이동하시고 담당자에게 알려주세요.", lang="ko") is None

    def test_neutral_sentence_returns_none(self):
        assert detect_category("ICU 담당자께 안내드립니다.", lang="ko") is None


# ──────────────────────────────────────────────
# English (en) — detect_category
# ──────────────────────────────────────────────

class TestDetectCategoryEnglish:

    def test_stop_administration(self):
        assert detect_category("Stop administration immediately.", lang="en") == BlockedCategory.DIRECT_MEDICAL_INSTRUCTION

    def test_discontinue_base(self):
        assert detect_category("Discontinue this medication.", lang="en") == BlockedCategory.DIRECT_MEDICAL_INSTRUCTION

    def test_discontinue_past(self):
        assert detect_category("Administration was discontinued.", lang="en") == BlockedCategory.DIRECT_MEDICAL_INSTRUCTION

    def test_discontinue_present_participle(self):
        assert detect_category("Discontinuing the medication is recommended.", lang="en") == BlockedCategory.DIRECT_MEDICAL_INSTRUCTION

    def test_do_not_administer(self):
        assert detect_category("Do not administer this product.", lang="en") == BlockedCategory.DIRECT_MEDICAL_INSTRUCTION

    def test_replace_with_another(self):
        assert detect_category("Replace with another medication.", lang="en") == BlockedCategory.SUBSTITUTION_RECOMMENDATION

    def test_switch_to(self):
        assert detect_category("Switch to a different formulation.", lang="en") == BlockedCategory.SUBSTITUTION_RECOMMENDATION

    def test_discard_affected(self):
        assert detect_category("Discard the affected inventory.", lang="en") == BlockedCategory.DISPOSAL_INSTRUCTION

    def test_dispose_of(self):
        assert detect_category("Dispose of the product immediately.", lang="en") == BlockedCategory.DISPOSAL_INSTRUCTION

    def test_safe_to_use(self):
        assert detect_category("The product is safe to use.", lang="en") == BlockedCategory.CERTAINTY_WITHOUT_APPROVAL

    def test_continue_use(self):
        assert detect_category("Continue use as directed.", lang="en") == BlockedCategory.CERTAINTY_WITHOUT_APPROVAL

    def test_safe_english_sentence_returns_none(self):
        assert detect_category("Quarantine the affected lot and notify the pharmacist.", lang="en") is None

    def test_case_insensitive(self):
        assert detect_category("DISCONTINUE IMMEDIATELY.", lang="en") == BlockedCategory.DIRECT_MEDICAL_INSTRUCTION


# ──────────────────────────────────────────────
# Bilingual (both) — detect_category
# ──────────────────────────────────────────────

class TestDetectCategoryBilingual:

    def test_korean_detected_in_both_mode(self):
        assert detect_category("투여 중단하세요.", lang="both") == BlockedCategory.DIRECT_MEDICAL_INSTRUCTION

    def test_english_detected_in_both_mode(self):
        assert detect_category("Discontinue this medication.", lang="both") == BlockedCategory.DIRECT_MEDICAL_INSTRUCTION

    def test_korean_disposal_in_both_mode(self):
        assert detect_category("폐기하세요.", lang="both") == BlockedCategory.DISPOSAL_INSTRUCTION

    def test_english_disposal_in_both_mode(self):
        assert detect_category("Discard the affected inventory.", lang="both") == BlockedCategory.DISPOSAL_INSTRUCTION

    def test_safe_sentence_returns_none_in_both_mode(self):
        assert detect_category("Quarantine the lot and notify the pharmacist.", lang="both") is None

    def test_default_lang_is_both(self):
        # lang 파라미터 없이 호출 시 both로 동작
        assert detect_category("투여 중단하세요.") == BlockedCategory.DIRECT_MEDICAL_INSTRUCTION
        assert detect_category("Discontinue this medication.") == BlockedCategory.DIRECT_MEDICAL_INSTRUCTION


# ──────────────────────────────────────────────
# scan_evidence_sentence (English only)
# ──────────────────────────────────────────────

class TestScanEvidenceSentence:

    def test_unsafe_english_sentence(self):
        assert scan_evidence_sentence("Discontinue use immediately.") == BlockedCategory.DIRECT_MEDICAL_INSTRUCTION

    def test_safe_english_sentence(self):
        assert scan_evidence_sentence("Quarantine the affected lot and notify the pharmacist.") is None

    def test_discard_evidence(self):
        assert scan_evidence_sentence("Discard the affected inventory.") == BlockedCategory.DISPOSAL_INSTRUCTION

    def test_replace_with_another(self):
        assert scan_evidence_sentence("Replace with another medication.") == BlockedCategory.SUBSTITUTION_RECOMMENDATION


# ──────────────────────────────────────────────
# draft_safety_check
# ──────────────────────────────────────────────

class TestDraftSafetyCheck:

    def test_unsafe_english_sentences_blocked(self):
        draft = "Please be advised regarding the recall.\nDiscontinue use immediately.\nDiscard all affected units."
        result = draft_safety_check(draft)

        assert result.needs_action_review is True
        assert len(result.blocked_sentences) == 2
        assert result.blocked_sentences[0].category == BlockedCategory.DIRECT_MEDICAL_INSTRUCTION
        assert result.blocked_sentences[1].category == BlockedCategory.DISPOSAL_INSTRUCTION

    def test_unsafe_korean_sentences_blocked(self):
        draft = "ICU 담당자께 안내드립니다.\n즉시 투여를 중단하세요.\n전량 폐기하세요."
        result = draft_safety_check(draft)

        assert result.needs_action_review is True
        assert len(result.blocked_sentences) == 2

    def test_mixed_language_draft_blocked(self):
        draft = "Please be advised.\n투여 중단하세요.\nDiscard all affected units."
        result = draft_safety_check(draft)

        assert result.needs_action_review is True
        assert len(result.blocked_sentences) == 2

    def test_safe_draft_not_blocked(self):
        draft = "Please be advised regarding the recall.\nQuarantine the affected lot and notify the pharmacist."
        result = draft_safety_check(draft)

        assert result.needs_action_review is False
        assert len(result.blocked_sentences) == 0
        assert result.revised_draft == draft

    def test_revised_draft_preserves_safe_sentences(self):
        draft = "Please be advised.\nDiscontinue use immediately.\nNotify the pharmacist."
        result = draft_safety_check(draft)

        assert "Please be advised." in result.revised_draft
        assert "Notify the pharmacist." in result.revised_draft
        assert "Discontinue use immediately." not in result.revised_draft
        assert "Please consult the pharmacist before taking action." in result.revised_draft

    def test_original_newlines_preserved(self):
        draft = "Please be advised.\nDiscontinue use immediately.\nNotify the pharmacist."
        result = draft_safety_check(draft)

        assert result.revised_draft.count("\n") == draft.count("\n")

    def test_blocked_sentence_replacement_text(self):
        draft = "Discard all affected units."
        result = draft_safety_check(draft)

        assert result.blocked_sentences[0].replaced_with == "Please consult the pharmacist before taking action."