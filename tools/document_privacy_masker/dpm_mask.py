"""문서 개인정보 마스킹 — 찾은 글자를 처리 방식대로 바꾼 글자.

한글(hwpx)은 이 글자로 바꿔 넣고, PDF 는 원래 글자를 지운 자리에 이 글자를 적는다.
"""
from __future__ import annotations

import re

from dpm_kinds import KEEP, MASK_PART

STAR = "*"
_KEEP_CHARS = set(" -.,/()[]:@\n\t")


def _stars(text: str) -> str:
    """구분 기호(-, ., 공백, 괄호)는 두고 글자·숫자만 * 로 바꾼다. 자리 수가 그대로 보인다."""
    return "".join(ch if ch in _KEEP_CHARS else STAR for ch in text)


def _digits_mask(text: str, keep_head: int = 0, keep_tail: int = 0) -> str:
    """숫자만 세어 앞 keep_head 개·뒤 keep_tail 개를 남기고 가린다."""
    positions = [i for i, ch in enumerate(text) if ch.isdigit()]
    hide = set(positions[keep_head:len(positions) - keep_tail if keep_tail else None])
    return "".join(STAR if i in hide else ch for i, ch in enumerate(text))


def _mask_name(text: str) -> str:
    # 김철수(金哲洙) → 김*수(***) / 남궁민수 → 남**수 / 이준 → 이*
    spaced = re.fullmatch(r"[가-힣](?:[ \t\u3000]+[가-힣]){1,3}", text)
    if spaced:
        # 글자 사이를 띄운 이름: 박 호 용 → 박 * 용 (빈칸은 그대로)
        idx = [i for i, ch in enumerate(text) if "가" <= ch <= "힣"]
        hide = set(idx[1:-1]) if len(idx) >= 3 else set(idx[1:])
        return "".join(STAR if i in hide else ch for i, ch in enumerate(text))
    m = re.match(r"([가-힣]+)(.*)$", text, re.S)
    if not m:
        return _stars(text)
    name, rest = m.group(1), m.group(2)
    if len(name) <= 2:
        masked = name[0] + STAR * (len(name) - 1)
    else:
        masked = name[0] + STAR * (len(name) - 2) + name[-1]
    rest = re.sub(r"[^\s()]", STAR, rest)
    return masked + rest


def _mask_phone(text: str) -> str:
    # 010-1234-5678 → 010-****-5678, 063-239-3114 → 063-***-3114
    groups = re.split(r"([^\d]+)", text)
    digit_groups = [i for i, g in enumerate(groups) if g.isdigit()]
    if len(digit_groups) >= 3:
        mid = digit_groups[1]
        groups[mid] = STAR * len(groups[mid])
        return "".join(groups)
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 10:
        return _digits_mask(text, keep_head=3, keep_tail=4)
    return _stars(text)


def _mask_email(text: str) -> str:
    local, _, domain = text.partition("@")
    keep = min(2, max(1, len(local) // 3))
    return local[:keep] + STAR * max(1, len(local) - keep) + "@" + domain


def _mask_address(text: str) -> str:
    # 시·도와 시·군·구까지만 남기고 나머지(도로명·번지·동·호수)는 가린다.
    tokens = re.split(r"(\s+)", text)
    out, keep = [], True
    for tok in tokens:
        if tok.isspace() or not tok:
            out.append(tok)
            continue
        if keep and re.fullmatch(r"[가-힣]+(?:특별시|광역시|특별자치시|특별자치도|도|시|군|구)", tok):
            out.append(tok)
            continue
        keep = False
        out.append(_stars(tok))
    return "".join(out)


def _mask_vehicle(text: str) -> str:
    return re.sub(r"\d{4}$", STAR * 4, text)


def _mask_rrn_part(text: str) -> str:
    # 880101-1234567 → 880101-1****** (생년월일·성별까지만)
    return _digits_mask(text, keep_head=7)


def _mask_account(text: str) -> str:
    return _digits_mask(text, keep_tail=4)


def _mask_birth(text: str) -> str:
    # 1978.03.02 → 1978.**.**
    parts = re.split(r"(\D+)", text)
    seen = 0
    for i, p in enumerate(parts):
        if p.isdigit():
            seen += 1
            if seen >= 2:
                parts[i] = STAR * len(p)
    return "".join(parts)


_PART = {
    "PERSON": _mask_name,
    "MOBILE": _mask_phone,
    "PHONE": _mask_phone,
    "EMAIL": _mask_email,
    "ADDRESS": _mask_address,
    "VEHICLE": _mask_vehicle,
    "RRN": _mask_rrn_part,
    "FRN": _mask_rrn_part,
    "ACCOUNT": _mask_account,
    "CARD": _mask_account,
    "BIRTH": _mask_birth,
}


def masked_text(kind: str, text: str, action: str) -> str:
    """처리 방식대로 바꾼 글자. '가리지 않음'이면 종류와 상관없이 원래 글자(사람이 확인 화면에서 고른 것)."""
    if action == KEEP:
        return text
    if action == MASK_PART:
        fn = _PART.get(kind)
        return fn(text) if fn else _stars(text)
    return _stars(text)
