"""
Integration test for NDC normalization.

Verifies that all 42 sample recall records are correctly normalized
to 11-digit NDC format, covering all three NDC segment patterns.

Run:
    pytest backend/tests/test_ndc_normalization.py -v
"""

import json
import re
from pathlib import Path

import pytest

from app.event.normalizer import normalize_ndc, normalize_event

# 샘플 데이터 경로
SAMPLE_PATH = Path(__file__).parent.parent / "app" / "event" / "recall_samples.json"


def load_samples() -> list[dict]:
    with open(SAMPLE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ──────────────────────────────────────────────
# 단위 테스트 — normalize_ndc()
# ──────────────────────────────────────────────

class TestNormalizeNdc:

    def test_4_4_2_format(self):
        """4-4-2 형식 → 앞에 0 추가해서 11자리"""
        assert normalize_ndc("0641-6014-41") == "00641601441"

    def test_5_3_2_format(self):
        """5-3-2 형식 → product 앞에 0 추가해서 11자리"""
        assert normalize_ndc("12345-678-90") == "12345067890"

    def test_5_4_1_format(self):
        """5-4-1 형식 → package 앞에 0 추가해서 11자리"""
        assert normalize_ndc("12345-6789-1") == "12345678901"

    def test_already_11_digits_no_hyphens(self):
        """이미 11자리 숫자 → 그대로"""
        assert normalize_ndc("00641601441") == "00641601441"

    def test_short_digits_no_hyphens(self):
        """하이픈 없는 짧은 숫자 → 앞에 0 채워서 11자리"""
        assert normalize_ndc("064160141") == "00064160141" # 9자리 → 11자리

    def test_invalid_segment_count_raises(self):
        """세그먼트가 3개가 아니면 ValueError"""
        with pytest.raises(ValueError):
            normalize_ndc("1234-5678")

    def test_invalid_length_raises(self):
        """11자리 초과 시 ValueError"""
        with pytest.raises(ValueError):
            normalize_ndc("123456789012")

    def test_output_is_exactly_11_digits(self):
        """출력값이 정확히 11자리 숫자인지"""
        result = normalize_ndc("0641-6014-41")
        assert len(result) == 11
        assert result.isdigit()


# ──────────────────────────────────────────────
# 통합 테스트 — 샘플 42개 전체 검증
# ──────────────────────────────────────────────

class TestNdcNormalizationIntegration:

    @pytest.fixture
    def samples(self):
        return load_samples()

    def test_sample_file_exists(self):
        """샘플 파일이 존재하는지"""
        assert SAMPLE_PATH.exists(), f"Sample file not found: {SAMPLE_PATH}"

    def test_sample_count(self, samples):
        """샘플이 42개인지"""
        assert len(samples) == 42, f"Expected 42 samples, got {len(samples)}"

    def test_all_ndcs_normalize_to_11_digits(self, samples):
        """42개 샘플 전부 11자리로 정규화되는지"""
        failed = []

        for sample in samples:
            raw_ndc = sample["product_ndc"]
            try:
                result = normalize_ndc(raw_ndc)
                if len(result) != 11 or not result.isdigit():
                    failed.append({
                        "recall_number": sample["recall_number"],
                        "raw_ndc": raw_ndc,
                        "result": result,
                        "reason": "Not 11 digits or contains non-digit"
                    })
            except ValueError as e:
                failed.append({
                    "recall_number": sample["recall_number"],
                    "raw_ndc": raw_ndc,
                    "result": None,
                    "reason": str(e)
                })

        assert not failed, (
            f"{len(failed)} NDC(s) failed normalization:\n" +
            "\n".join(
                f"  [{f['recall_number']}] {f['raw_ndc']} → {f['result']} ({f['reason']})"
                for f in failed
            )
        )

    def test_all_ndcs_digits_only_after_normalization(self, samples):
        """정규화 결과가 숫자만 포함하는지"""
        for sample in samples:
            result = normalize_ndc(sample["product_ndc"])
            assert re.fullmatch(r'\d{11}', result), (
                f"[{sample['recall_number']}] NDC {sample['product_ndc']} → "
                f"{result} is not 11 digits"
            )

    def test_full_event_normalization_succeeds(self, samples):
        """42개 샘플 전체가 normalize_event() 통과하는지"""
        failed = []

        for sample in samples:
            try:
                event = normalize_event(sample)
                assert len(event.ndc) == 11
                assert event.ndc.isdigit()
                assert event.drug_name  # 약물명이 비어있으면 안 됨
            except Exception as e:
                failed.append({
                    "recall_number": sample["recall_number"],
                    "reason": str(e)
                })

        assert not failed, (
            f"{len(failed)} sample(s) failed full normalization:\n" +
            "\n".join(
                f"  [{f['recall_number']}] {f['reason']}"
                for f in failed
            )
        )

    def test_drug_names_are_lowercase(self, samples):
        """정규화된 약물명이 소문자인지"""
        for sample in samples:
            event = normalize_event(sample)
            assert event.drug_name == event.drug_name.lower(), (
                f"[{sample['recall_number']}] drug_name '{event.drug_name}' is not lowercase"
            )

    def test_drug_names_not_empty(self, samples):
        """정규화된 약물명이 비어있지 않은지"""
        for sample in samples:
            event = normalize_event(sample)
            assert event.drug_name.strip(), (
                f"[{sample['recall_number']}] drug_name is empty after normalization"
            )
