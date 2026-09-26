"""문서 개인정보 마스킹 — 개인정보 종류와 기본 처리 방식.

이 도구 안에서만 쓰는 모듈이다. 다른 도구의 모듈과 이름이 겹치지 않게
모든 내부 모듈 이름을 dpm_ 으로 시작한다(도구 폴더가 같은 sys.path 에 올라간다).
"""
from __future__ import annotations

from dataclasses import dataclass


# 처리 방식
MASK_ALL = "mask_all"      # 전부 가림:   880101-1234567 → **************
MASK_PART = "mask_part"    # 일부 가림:   010-1234-5678  → 010-****-5678
REPLACE = "replace"        # 종류로 바꿈: 홍길동         → [성명]
KEEP = "keep"              # 가리지 않음

ACTION_LABELS = {
    MASK_ALL: "전부 가림",
    MASK_PART: "일부 가림",
    REPLACE: "종류로 바꿈",
    KEEP: "가리지 않음",
}


@dataclass(frozen=True)
class Kind:
    code: str
    label: str
    default_action: str
    # 법으로 공개가 금지된 고유식별정보·금융정보 등. 화면에 자물쇠로 표시하고, 다시 검사 때 가려지지 않은 채 남았는지 따로 알린다.
    fixed: bool = False


KINDS: dict[str, Kind] = {k.code: k for k in (
    # 법정 비공개 고정 7종 (KID 의 분류를 따름)
    Kind("RRN", "주민등록번호", MASK_ALL, fixed=True),
    Kind("FRN", "외국인등록번호", MASK_ALL, fixed=True),
    Kind("CARD", "카드번호", MASK_ALL, fixed=True),
    Kind("MOBILE", "휴대전화", MASK_PART, fixed=True),
    Kind("ACCOUNT", "계좌번호", MASK_ALL, fixed=True),
    Kind("PASSPORT", "여권번호", MASK_ALL, fixed=True),
    Kind("DRIVER", "운전면허번호", MASK_ALL, fixed=True),
    # 판단이 필요한 항목
    Kind("PERSON", "성명", MASK_PART),
    Kind("ADDRESS", "주소", MASK_PART),
    Kind("BIRTH", "생년월일", MASK_ALL),
    Kind("PHONE", "일반전화", MASK_PART),
    Kind("EMAIL", "이메일", MASK_PART),
    Kind("BIZ", "사업자등록번호", REPLACE),
    Kind("VEHICLE", "차량번호", MASK_PART),
    Kind("EMPLOYEE_ID", "사번", MASK_ALL),
    Kind("CUSTOM", "직접 추가", MASK_ALL),
)}

# 법정 7종: 확인 화면에 자물쇠로 표시한다.
FIXED_CODES = frozenset(code for code, kind in KINDS.items() if kind.fixed)

# ko-pii 라벨 → 이 도구의 종류. 여기 없는 라벨(학력·직책·나이 등)은 쓰지 않는다.
KO_PII_LABELS = {
    "RRN": "RRN",
    "FRN": "FRN",
    "CARD": "CARD",
    "ACCOUNT": "ACCOUNT",
    "PASSPORT": "PASSPORT",
    "DRIVER_LICENSE": "DRIVER",
    "PERSON": "PERSON",
    "ADDRESS": "ADDRESS",
    "DT_BIRTH": "BIRTH",
    "PHONE": "PHONE",      # 휴대전화/일반전화는 번호 앞자리로 다시 나눈다.
    "FAX": "PHONE",
    "EMAIL": "EMAIL",
    "BUSINESS_REG": "BIZ",
    "VEHICLE": "VEHICLE",
    "EMPLOYEE_ID": "EMPLOYEE_ID",
}


def label_of(code: str) -> str:
    kind = KINDS.get(code)
    return kind.label if kind else code
