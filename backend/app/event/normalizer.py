"""
P1 - Event Normalizer

Converts raw FDA recall JSON into EventNormalized schema.
- Extracts generic drug name from product description
- Converts NDC to 11-digit standard format
- Maps classification string to Classification enum
"""

import re
from datetime import date

from app.schemas.common import Classification, EventType
from app.schemas.event import EventNormalized


# 제거할 제형 목록 (dosage forms)
DOSE_FORMS = [
    "injection", "injectable", "emulsion", "solution",
    "powder", "tablet", "tablets", "capsule", "capsules",
    "syrup", "suspension", "cream", "ointment", "patch",
    "infusion", "concentrate", "oral", "iv", "bag",
    "vial", "vials", "ampule", "ampules", "ampuls",
    "syringe", "syringes", "for",
]

# 제거할 염/부가어 목록 (salt forms)
SALT_FORMS = [
    "hydrochloride", "hcl", "sodium", "sulfate", "bitartrate",
    "citrate", "phosphate", "succinate", "tromethamine",
    "gluconate", "acetate", "bromide", "chloride", "nitrate",
]

# Classification 문자열 → enum 매핑
CLASSIFICATION_MAP = {
    "class i": Classification.CLASS_I,
    "class ii": Classification.CLASS_II,
    "class iii": Classification.CLASS_III,
}


def normalize_drug_name(raw_name: str) -> str:
    """
    약물명에서 용량, 제형, 염 형태를 제거하고 generic name만 추출.

    예시:
        "MIDAZOLAM HCl 1mg/mL Injection, 10mL vials" → "midazolam"
        "Vancomycin HCl 500mg powder for injection"   → "vancomycin"
        "Heparin Sodium 5000 USP units/mL Injection"  → "heparin"
    """
    name = raw_name.lower().strip()

    # 1. 콤마 이후 제거 (예: "1mg/mL Injection, 10mL vials" → "10mL vials" 부분 제거)
    name = name.split(",")[0]

    # 2. 용량 제거
    # 숫자 + 단위 패턴 (예: 1mg/mL, 500mg, 5000 USP units/mL, 0.05mcg, 50%)
    name = re.sub(
        r'\d+\.?\d*\s*(mg|mcg|g|ml|l|units?|usp\s*units?|iu|meq|%)[\s\/\w]*',
        ' ', name
    )

    # 3. 괄호 안 내용 제거 (예: (1:1000), (1:10000))
    name = re.sub(r'\(.*?\)', '', name)

    # 4. 제형 제거
    for form in DOSE_FORMS:
        name = re.sub(rf'\b{re.escape(form)}\b', ' ', name)

    # 5. 염 형태 제거
    for salt in SALT_FORMS:
        name = re.sub(rf'\b{re.escape(salt)}\b', ' ', name)

    # 6. 공백 정리
    name = re.sub(r'\s+', ' ', name).strip()

    return name


def normalize_ndc(raw_ndc: str) -> str:
    """
    다양한 형식의 NDC를 11자리 표준 형식으로 변환.
    세그먼트 구조를 인식해서 올바른 자리에 0을 채움.

    FDA NDC 형식 3가지:
        4-4-2 → labeler(4) + product(4) + package(2) → labeler에 0 1개 추가
        5-3-2 → labeler(5) + product(3) + package(2) → product에 0 1개 추가
        5-4-1 → labeler(5) + product(4) + package(1) → package에 0 1개 추가

    예시:
        "0641-6014-41"   → "00641601441"  (4-4-2)
        "12345-678-90"   → "12345067890"  (5-3-2)
        "12345-6789-1"   → "12345678901"  (5-4-1)
        "00641601441"    → "00641601441"  (이미 11자리)
    """
    raw_ndc = raw_ndc.strip()

    # 하이픈이 있으면 세그먼트 구조 인식
    if "-" in raw_ndc:
        segments = raw_ndc.split("-")

        if len(segments) != 3:
            raise ValueError(
                f"NDC must have 3 segments separated by hyphens. "
                f"Received: {raw_ndc!r}"
            )

        labeler, product, package = segments
        seg_lengths = (len(labeler), len(product), len(package))

        # 세그먼트 길이 기준으로 0 패딩 위치 결정
        if seg_lengths == (4, 4, 2):
            # 4-4-2 → labeler 앞에 0 추가
            labeler = labeler.zfill(5)
        elif seg_lengths == (5, 3, 2):
            # 5-3-2 → product 앞에 0 추가
            product = product.zfill(4)
        elif seg_lengths == (5, 4, 1):
            # 5-4-1 → package 앞에 0 추가
            package = package.zfill(2)
        elif seg_lengths == (5, 4, 2):
            # 이미 올바른 형식
            pass
        else:
            raise ValueError(
                f"Unrecognized NDC segment pattern {seg_lengths}. "
                f"Received: {raw_ndc!r}"
            )

        digits = labeler + product + package

    else:
        # 하이픈 없는 경우 — 자리수로 판단
        digits = re.sub(r'\s', '', raw_ndc)
        if len(digits) < 11:
            digits = digits.zfill(11)

    if len(digits) != 11:
        raise ValueError(
            f"NDC must be 11 digits after normalization. "
            f"Received: {raw_ndc!r} → {digits!r} ({len(digits)} digits)"
        )

    return digits


def normalize_classification(raw: str | None) -> Classification | None:
    """
    분류 문자열을 Classification enum으로 변환.

    예시:
        "Class I"   → Classification.CLASS_I
        "Class II"  → Classification.CLASS_II
        "Class III" → Classification.CLASS_III
        None        → None
    """
    if not raw:
        return None
    return CLASSIFICATION_MAP.get(raw.lower().strip())


def normalize_event(raw: dict) -> EventNormalized:
    """
    FDA 원본 recall JSON 하나를 받아서 EventNormalized로 변환.

    Args:
        raw: FDA recall JSON 딕셔너리 (recall_samples.json의 항목 하나)

    Returns:
        EventNormalized: 정규화된 이벤트 스키마

    예시 입력:
        {
            "recall_number": "D-001-2026",
            "product_description": "Midazolam HCl 1mg/mL Injection, 10mL vials",
            "classification": "Class I",
            "product_ndc": "0641-6014-41",
            "lot_number": "LOT-A1",
            "recall_initiation_date": "2026-01-10",
            "status": "ongoing"
        }

    예시 출력:
        EventNormalized(
            event_id="D-001-2026",
            event_type=EventType.RECALL,
            drug_name="midazolam",
            ndc="00641601441",
            lot="LOT-A1",
            classification=Classification.CLASS_I,
            status="ongoing",
            recall_initiation_date=date(2026, 1, 10)
        )
    """
    drug_name = normalize_drug_name(raw["product_description"])
    ndc = normalize_ndc(raw["product_ndc"])
    classification = normalize_classification(raw.get("classification"))

    # 날짜 변환 ("2026-01-10" → date 객체)
    raw_date = raw.get("recall_initiation_date")
    recall_date = date.fromisoformat(raw_date) if raw_date else None

    return EventNormalized(
        event_id=raw["recall_number"],
        event_type=EventType.RECALL,
        drug_name=drug_name,
        ndc=ndc,
        lot=raw.get("lot_number"),
        classification=classification,
        status=raw.get("status", "ongoing"),
        recall_initiation_date=recall_date,
    )
