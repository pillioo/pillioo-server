"""
P1 - Event Normalizer

Converts raw FDA recall JSON into EventNormalized schema.
- Extracts generic drug name from product description
- Converts NDC to 11-digit standard format
- Maps classification string to Classification enum
"""

import json
import re
from datetime import date
from pathlib import Path

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
# sodium, chloride 원복 — protected_compounds.json으로 예외 처리
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

# protected_compounds.json 경로
_PROTECTED_PATH = Path(__file__).parent / "protected_compounds.json"


def _load_protected_compounds() -> set[str]:
    """
    protected_compounds.json에서 예외 화합물 목록을 로드.
    파일이 없으면 FileNotFoundError 발생.
    """
    if not _PROTECTED_PATH.exists():
        raise FileNotFoundError(
            f"Required protected compounds file not found: {_PROTECTED_PATH}"
        )
    with open(_PROTECTED_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {compound.strip().lower() for compound in data["protected_compounds"]}


# 모듈 로드 시 한 번만 읽음
PROTECTED_COMPOUNDS = _load_protected_compounds()


def _strip_salt(name: str) -> str:
    """
    제형 제거까지 끝난 단일 화합물명에 대해
    protected 여부 체크 후 salt 제거.

    예시:
        "heparin sodium"   → "heparin sodium"  (protected)
        "sodium chloride"  → "sodium chloride"  (protected)
        "morphine sulfate" → "morphine"         (not protected)
        "midazolam hcl"    → "midazolam"        (not protected)
    """
    if name in PROTECTED_COMPOUNDS:
        return name
    for salt in SALT_FORMS:
        name = re.sub(rf'\b{re.escape(salt)}\b', ' ', name)
    return re.sub(r'\s+', ' ', name).strip()


def _sanitize_component(component: str) -> str:
    """
    단일 화합물 컴포넌트 정규화 — 용량/제형 제거 후 salt 제거.

    예시:
        "Piperacillin 4.5g powder for injection" → "piperacillin"
        "Tazobactam"                             → "tazobactam"
    """
    # 1. 용량 제거
    component = re.sub(
        r'\d+\.?\d*\s*(mg|mcg|g|ml|l|units?|usp\s*units?|iu|meq|%)[\s\/\w]*',
        ' ', component
    )
    # 2. 괄호 안 내용 제거
    component = re.sub(r'\(.*?\)', '', component)
    # 3. 제형 제거
    for form in DOSE_FORMS:
        component = re.sub(rf'\b{re.escape(form)}\b', ' ', component)
    # 4. 공백 정리
    component = re.sub(r'\s+', ' ', component).strip()
    # 5. protected 체크 후 salt 제거
    return _strip_salt(component)


def sanitize_drug_name(raw_name: str) -> str:
    """
    약물명에서 용량, 제형, 염 형태를 제거하고 generic name만 추출.

    복합제(combination drug)는 "and" 기준으로 컴포넌트 분리 후
    각각 정규화해서 "A / B" 형식으로 합침.
    → RAG pipeline RxNorm 결과와 형식 통일.

    (참고: EventNormalized.normalize_drug_name field_validator와 이름이
    겹치지 않도록 sanitize_drug_name으로 명명함.)

    예시:
        "MIDAZOLAM HCl 1mg/mL Injection, 10mL vials"           → "midazolam"
        "Piperacillin and Tazobactam 4.5g powder for injection" → "piperacillin / tazobactam"
        "Heparin Sodium 5000 USP units/mL Injection"            → "heparin sodium"  (protected)
        "Sodium Chloride 0.9% Injection, 100mL bags"            → "sodium chloride" (protected)
        "Morphine Sulfate 10mg/mL Injection"                    → "morphine"
    """
    name = raw_name.lower().strip()

    # 1. 콤마 이후 제거
    name = name.split(",")[0]

    # 2. 복합제 처리: "and" 기준으로 컴포넌트 분리 후 각각 정규화
    # 예: "piperacillin and tazobactam" → "piperacillin / tazobactam"
    parts = re.split(r'\s+and\s+', name)
    if len(parts) > 1:
        return ' / '.join(_sanitize_component(p.strip()) for p in parts)

    # 3. 단일 화합물
    return _sanitize_component(name)


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

    if "-" in raw_ndc:
        segments = raw_ndc.split("-")

        if len(segments) != 3:
            raise ValueError(
                f"NDC must have 3 segments separated by hyphens. "
                f"Received: {raw_ndc!r}"
            )

        labeler, product, package = segments
        seg_lengths = (len(labeler), len(product), len(package))

        if seg_lengths == (4, 4, 2):
            labeler = labeler.zfill(5)
        elif seg_lengths == (5, 3, 2):
            product = product.zfill(4)
        elif seg_lengths == (5, 4, 1):
            package = package.zfill(2)
        elif seg_lengths == (5, 4, 2):
            pass
        else:
            raise ValueError(
                f"Unrecognized NDC segment pattern {seg_lengths}. "
                f"Received: {raw_ndc!r}"
            )

        digits = labeler + product + package

    else:
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
    """
    drug_name = sanitize_drug_name(raw["product_description"])
    ndc = normalize_ndc(raw["product_ndc"])
    classification = normalize_classification(raw.get("classification"))

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
        recall_number=raw["recall_number"],
        product_description=raw["product_description"],
        reason_for_recall=raw.get("reason_for_recall"),
    )