"""문서 개인정보 마스킹 — 개인정보 찾기.

두 겹으로 찾는다.
  1) ko-pii (MIT, Marker Inc Korea): 규칙·사전·체크섬 기반 한국어 개인정보 검출.
     vendor/ko_pii 에 그대로 넣어 두었다(외부 의존성 없음).
  2) 인사 서류에서 자주 나오지만 ko-pii 가 놓치는 모양을 이 도구의 규칙으로 보강한다.
     (safeDoc·KID·k-polishield 의 방식을 참고. 출처는 NOTICE.md)
       - 한자 병기 이름      김철수(金哲洙)
       - 관계·역할 뒤 이름   배우자 이영희, 예금주: 박영수
       - 세로로 풀린 표      성명 / 홍길동 / 김영희 …
       - 일부 가린 주민번호  750302-2******
       - 검증식이 안 맞아도 항목명 옆의 주민번호·카드·사업자번호
       - 옛 시·도 이름과 상세주소(동·호수, 괄호 속 건물명)
       - 표 머리글로 열 전체 판단(성명·주민등록번호·주소·연락처·계좌 …)

찾기는 '빠뜨리지 않는 쪽'(재현율 우선)으로 잡는다. 최종 판단은 사람이 확인 화면에서 한다.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dpm_kinds import FIXED_CODES, KINDS, KO_PII_LABELS, label_of

_VENDOR = Path(__file__).resolve().parent / "vendor"
if str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))

from ko_pii import detect_all as _ko_detect_all  # noqa: E402
from ko_pii.dictionaries.surnames import surname_prefix_len  # noqa: E402
from ko_pii.dictionaries.field_labels import is_field_label  # noqa: E402

try:  # 흔한 낱말(이름처럼 생긴 일반어) 사전. 없으면 건너뛴다.
    from ko_pii.dictionaries.common_words import is_common_word  # noqa: E402
except Exception:  # pragma: no cover
    def is_common_word(token: str) -> bool:  # type: ignore[misc]
        return False


# ---------------------------------------------------------------- 결과 모양

@dataclass
class Finding:
    kind: str
    start: int
    end: int
    text: str
    confidence: float
    reasons: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return label_of(self.kind)

    @property
    def fixed(self) -> bool:
        return self.kind in FIXED_CODES

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "label": self.label,
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "confidence": round(self.confidence, 2),
            "reasons": list(self.reasons),
            "fixed": self.fixed,
            "action": KINDS[self.kind].default_action if self.kind in KINDS else "mask_all",
        }


# ---------------------------------------------------------------- 공통 도우미

_HANGUL_NAME = r"[가-힣]{2,4}"
# 이름 자리에 자주 오지만 이름이 아닌 낱말
_NOT_NAMES = frozenset({
    "동행", "주무관", "사무관", "서기관", "교사", "교감", "교장", "원장", "원감", "과장", "팀장", "국장",
    "실장", "부장", "차장", "계장", "주사", "주사보", "서기", "행정실장", "담임", "학생", "학부모",
    "본인", "배우자", "자녀", "없음", "해당없음", "미정", "공란", "생략",
    "위원장", "부위원장", "방과후", "전일제", "돌봄", "기간제", "계약제", "시간제", "정규직", "원어민",
    "보조", "협력", "전담", "보건", "상담", "영양", "특수", "순회", "수석", "선임", "외부", "내부", "신규",
    "부담금", "선정", "주의", "모님", "부모", "부모님",
})
# 이름 끝에 잘 오지 않는 두 글자(조사·어미)
_NOT_NAME_ENDINGS = (
    "까지", "부터", "하기", "하며", "하고", "하여", "하는", "되는", "있는", "없는", "에게", "에서", "으로",
    "처럼", "드리", "리며", "할지", "한다", "니다", "하게", "해서", "위해", "대한", "관한", "통해",
)
_HANJA = r"[㐀-䶿一-鿿豈-﫿]"
_MASK_CHARS = "*＊xX●○◯■□◆◇"


def _near_before(text: str, start: int, words: tuple[str, ...], span: int = 20) -> bool:
    before = re.sub(r"\s+", "", text[max(0, start - span):start])
    return any(re.sub(r"\s+", "", w) in before for w in words)


# 성씨 한자 → 한글 음. '국지(局地)'·'원격지(遠隔地)' 같은 한자어를 이름으로 오해하지 않도록
# 괄호 속 첫 한자가 성씨 한자이고 그 음이 한글 이름 첫 글자와 같을 때만 한자 병기 이름으로 본다(KID 방식).
_SURNAME_HANJA = {
    "金": "김", "李": "이", "朴": "박", "崔": "최", "鄭": "정", "丁": "정", "程": "정", "姜": "강", "康": "강", "趙": "조",
    "曺": "조", "曹": "조", "尹": "윤", "張": "장", "蔣": "장", "莊": "장", "林": "임", "任": "임", "韓": "한",
    "吳": "오", "申": "신", "辛": "신", "愼": "신", "徐": "서", "權": "권", "黃": "황", "安": "안", "宋": "송",
    "柳": "류", "劉": "유", "兪": "유", "庾": "유", "全": "전", "田": "전", "錢": "전", "洪": "홍", "高": "고",
    "文": "문", "孫": "손", "梁": "양", "楊": "양", "裵": "배", "裴": "배", "白": "백", "許": "허", "南": "남",
    "沈": "심", "盧": "노", "魯": "노", "河": "하", "郭": "곽", "成": "성", "車": "차", "朱": "주", "周": "주",
    "禹": "우", "具": "구", "丘": "구", "羅": "나", "閔": "민", "陳": "진", "秦": "진", "晉": "진", "池": "지",
    "嚴": "엄", "蔡": "채", "元": "원", "袁": "원", "千": "천", "方": "방", "房": "방", "孔": "공", "玄": "현",
    "咸": "함", "卞": "변", "邊": "변", "廉": "염", "呂": "여", "余": "여", "秋": "추", "都": "도", "蘇": "소",
    "石": "석", "宣": "선", "薛": "설", "馬": "마", "吉": "길", "延": "연", "表": "표", "明": "명", "王": "왕",
    "潘": "반", "玉": "옥", "琴": "금", "孟": "맹", "諸": "제", "卓": "탁", "陸": "육", "魏": "위", "鞠": "국",
    "奇": "기", "殷": "은", "片": "편", "龍": "용", "睦": "목", "印": "인", "慶": "경", "賓": "빈", "夫": "부",
    "皇": "황", "甫": "보", "諸葛": "제갈", "南宮": "남궁", "鮮": "선", "司": "사", "獨": "독", "東": "동",
    "太": "태", "桂": "계", "牟": "모", "宋": "송", "奉": "봉", "晋": "진", "昔": "석", "董": "동", "葉": "엽",
    "承": "승", "邢": "형", "景": "경", "包": "포", "丙": "병", "占": "점", "伊": "이", "耿": "경", "杜": "두",
    "韋": "위", "雍": "옹", "于": "우", "艾": "애", "芮": "예", "國": "국", "凡": "범", "賈": "가", "簡": "간",
}


def _hanja_surname_ok(name: str, hanja: str) -> bool:
    if not re.search(_HANJA, hanja):
        return False
    for size in (2, 1):
        reading = _SURNAME_HANJA.get(hanja[:size])
        if reading and name.startswith(reading):
            return True
    return False


def _odd_four(token: str) -> bool:
    """외자 성(김·이…)으로 시작하는 네 글자 — 이름보다 일반어(감정코칭)일 때가 많다."""
    return len(token) == 4 and surname_prefix_len(token) == 1


def _looks_like_name(token: str) -> bool:
    if not re.fullmatch(_HANGUL_NAME, token):
        return False
    # '연락처'·'주소'·'성명' 같은 항목 이름, 직위, 문장 어미로 끝나는 낱말은 이름이 아니다.
    if is_field_label(token) or header_kind(token) or token in _NOT_NAMES:
        return False
    if token.endswith(_NOT_NAME_ENDINGS) or any(token.endswith(t) for t in _TITLES if len(t) >= 2):
        return False
    n = surname_prefix_len(token)
    if n == 0 or len(token) - n < 1:
        return False
    return not is_common_word(token)


def _rrn_checksum_ok(digits: str) -> bool:
    if len(digits) != 13 or not digits.isdigit():
        return False
    weights = (2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5)
    total = sum(int(d) * w for d, w in zip(digits[:12], weights))
    return (11 - total % 11) % 10 == int(digits[12])


def _plausible_birth(yy: str, mm: str, dd: str) -> bool:
    try:
        return 1 <= int(mm) <= 12 and 1 <= int(dd) <= 31
    except ValueError:
        return False


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def _biz_checksum_ok(digits: str) -> bool:
    if len(digits) != 10 or not digits.isdigit():
        return False
    weights = (1, 3, 7, 1, 3, 7, 1, 3, 5)
    total = sum(int(d) * w for d, w in zip(digits[:9], weights))
    total += int(digits[8]) * 5 // 10
    return (10 - total % 10) % 10 == int(digits[9])


# ---------------------------------------------------------------- 1) ko-pii

def _from_ko_pii(text: str) -> list[Finding]:
    out: list[Finding] = []
    for r in _ko_detect_all(text, include=list(KO_PII_LABELS)):
        kind = KO_PII_LABELS.get(r.label)
        if kind is None:
            continue
        value = text[r.start:r.end]
        if kind == "PHONE" and re.sub(r"\D", "", value).startswith(("010", "011", "016", "017", "018", "019")):
            kind = "MOBILE"
        out.append(Finding(kind, r.start, r.end, value, float(r.confidence), [f"ko-pii {label_of(kind)} 규칙"]))
    return [f for f in out if _keep_ko_pii(text, f)]


# 사람 이름 바로 뒤에 오는 직위·호칭. ko-pii 의 이름 후보는 실제 공문에서 '연수·가정·유아' 같은
# 일반어를 많이 잡아서, 이 도구에서는 호칭이 붙었거나 이름 항목 옆일 때만 받아들인다.
_TITLES = (
    "주무관", "사무관", "서기관", "이사관", "부이사관", "주사보", "주사", "서기보", "서기",
    "교사", "교감", "교장", "원장", "원감", "선생님", "선생", "강사", "교수", "교육장", "교육감",
    "장학사", "장학관", "연구사", "연구관", "교육연구사", "교육연구관", "사서", "영양사", "조리사",
    "조리실무사", "간호사", "행정실장", "실무사", "주임", "대리", "과장", "팀장", "국장", "실장",
    "부장", "차장", "계장", "위원장", "위원", "대표", "이사", "기자", "의원", "변호사", "학생",
    "학부모", "어머니", "아버지", "씨", "님", "군", "양",
)
_TITLE_RE = re.compile(r"\s?(?:" + "|".join(sorted(_TITLES, key=len, reverse=True)) + r")(?![가-힣])")


def _keep_ko_pii(text: str, f: Finding) -> bool:
    if f.kind == "PERSON":
        if f.text in _NOT_NAMES or _bad_person(text, f):
            return False
        if not _looks_like_name(f.text):
            return False
        # 두 글자·외자 성 네 글자는 일반어일 때가 많다('부위원장' → '부위'+'원장'). 호칭 판단에서 뺀다.
        if (len(f.text) == 2 or _odd_four(f.text)) and not re.match(r"\s?(?:씨|님)(?![가-힣])", text[f.end:]):
            before = text[max(0, f.start - 12):f.start]
            return any(label in before for label in ("성명", "이름", "성 명", "이 름", "성함"))
        if _TITLE_RE.match(text, f.end):
            f.reasons.append("이름 뒤 직위·호칭")
            return True
        before = text[max(0, f.start - 12):f.start]
        return any(label in before for label in ("성명", "이름", "성 명", "이 름", "성함"))
    if f.kind == "BIRTH":
        # ko-pii 는 날짜를 넓게 생년월일로 본다. 생년월일 항목 옆이거나 '생'이 붙은 것만.
        return _near_before(text, f.start, _BIRTH_LABELS, span=12) or text[f.end:f.end + 2].strip().startswith("생")
    if f.kind == "ADDRESS":
        # '제주', '경주시' 같은 지명 한 단어는 주소가 아니다.
        return bool(re.search(r"\d", f.text)) or len(re.findall(r"(시|군|구|읍|면|동|리|로|길)(?=\s|$)", f.text)) >= 2
    if f.kind == "VEHICLE":
        return bool(re.fullmatch(r"\d{2,3} ?[가-힣] ?\d{4}", f.text))
    return True


# 부서·기관 이름 뒤에 문서번호가 붙는 '정책기획과-12345' 를 이름으로 잡는 경우를 거른다.
_ORG_TAIL = re.compile(r"^[과팀실국청원소부처단관][-‐–]?\d")


def _bad_person(text: str, f: Finding) -> bool:
    if f.kind != "PERSON":
        return False
    if f.text in _NOT_NAMES:
        return True
    after = text[f.end:f.end + 3]
    return bool(_ORG_TAIL.match(after))


# ---------------------------------------------------------------- 2) 보강 규칙

_RRN_LABELS = ("주민등록번호", "주민번호", "주민등록 번호", "생년월일및성별")
_RRN_RE = re.compile(
    r"(?<![\d])(\d{2})(\d{2})(\d{2})\s?[-–‐]\s?([1-8])(\d{6}|[" + re.escape(_MASK_CHARS) + r"]{6})(?![\d])"
)
_RRN_NOHYPHEN_RE = re.compile(r"(?<!\d)(\d{2})(\d{2})(\d{2})([1-8]\d{6})(?!\d)")


def _rule_rrn(text: str) -> list[Finding]:
    out = []
    for m in _RRN_RE.finditer(text):
        yy, mm, dd, sex, tail = m.groups()
        if not _plausible_birth(yy, mm, dd):
            continue
        kind = "FRN" if sex in "5678" else "RRN"
        labeled = _near_before(text, m.start(), _RRN_LABELS + ("외국인등록번호", "등록번호"))
        if not tail.isdigit():
            out.append(Finding(kind, m.start(), m.end(), m.group(0), 0.85, ["뒷자리 일부가 이미 가려진 주민번호"]))
            continue
        if _rrn_checksum_ok(yy + mm + dd + sex + tail):
            out.append(Finding(kind, m.start(), m.end(), m.group(0), 0.95, ["주민번호 검증식 일치"]))
        else:
            reason = "주민번호 항목 옆(검증식 불일치)" if labeled else "주민번호 모양(검증식 불일치)"
            out.append(Finding(kind, m.start(), m.end(), m.group(0), 0.8 if labeled else 0.6, [reason]))
    for m in _RRN_NOHYPHEN_RE.finditer(text):
        yy, mm, dd, rest = m.groups()
        if not _plausible_birth(yy, mm, dd):
            continue
        if _near_before(text, m.start(), _RRN_LABELS) or _rrn_checksum_ok(m.group(0)):
            kind = "FRN" if rest[0] in "5678" else "RRN"
            out.append(Finding(kind, m.start(), m.end(), m.group(0), 0.8, ["붙여 쓴 13자리 주민번호"]))
    return out


_MOBILE_RE = re.compile(r"(?<!\d)01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}(?!\d)")
_PHONE_RE = re.compile(r"(?<!\d)0(?:2|[3-6]\d|70)[-.\s)]\s?\d{3,4}[-.\s]\d{4}(?!\d)")


def _rule_phone(text: str) -> list[Finding]:
    out = [Finding("MOBILE", m.start(), m.end(), m.group(0), 0.9, ["휴대전화 번호 모양"]) for m in _MOBILE_RE.finditer(text)]
    out += [Finding("PHONE", m.start(), m.end(), m.group(0), 0.8, ["전화번호 모양"]) for m in _PHONE_RE.finditer(text)]
    return out


_CARD_RE = re.compile(r"(?<!\d)\d{4}[- ]\d{4}[- ]\d{4}[- ]\d{4}(?!\d)")


def _rule_card(text: str) -> list[Finding]:
    out = []
    for m in _CARD_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if _luhn_ok(digits):
            out.append(Finding("CARD", m.start(), m.end(), m.group(0), 0.9, ["카드번호 검증식 일치"]))
        elif _near_before(text, m.start(), ("카드",)):
            out.append(Finding("CARD", m.start(), m.end(), m.group(0), 0.7, ["카드 항목 옆 16자리 번호"]))
    return out


_BANKS = ("국민", "신한", "우리", "하나", "농협", "기업", "수협", "우체국", "새마을", "신협", "산업", "씨티",
          "SC제일", "제일", "카카오", "케이뱅크", "토스", "대구", "부산", "경남", "광주", "전북", "제주", "iM")
_ACCOUNT_LABELS = ("계좌번호", "계좌", "통장", "입금", "예금주", "급여이체", "이체", "은행") + tuple(b + "은행" for b in _BANKS)
_ACCOUNT_RE = re.compile(r"(?<![\d-])\d{2,6}(?:[-\s]\d{2,8}){1,4}(?![\d-])|(?<!\d)\d{10,16}(?!\d)")


def _rule_account(text: str) -> list[Finding]:
    out = []
    for m in _ACCOUNT_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if not 10 <= len(digits) <= 16:
            continue
        before = text[max(0, m.start() - 25):m.start()]
        if any(w in before for w in _ACCOUNT_LABELS) or any(b in before[-8:] for b in _BANKS):
            out.append(Finding("ACCOUNT", m.start(), m.end(), m.group(0), 0.85, ["계좌·은행 항목 옆 번호"]))
    return out


_BIZ_RE = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{5}(?!\d)")


def _rule_biz(text: str) -> list[Finding]:
    out = []
    for m in _BIZ_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if _biz_checksum_ok(digits):
            out.append(Finding("BIZ", m.start(), m.end(), m.group(0), 0.9, ["사업자번호 검증식 일치"]))
        elif _near_before(text, m.start(), ("사업자",)):
            out.append(Finding("BIZ", m.start(), m.end(), m.group(0), 0.7, ["사업자 항목 옆 번호"]))
    return out


_BIRTH_LABELS = ("생년월일", "생 년 월 일", "출생일", "생일")
_DATE_RE = re.compile(
    r"(?<!\d)(?:19|20)?\d{2} ?[.\-/년] ?\d{1,2} ?[.\-/월] ?\d{1,2} ?[.일]?(?: ?생)?(?!\d)"
)


def _rule_birth(text: str) -> list[Finding]:
    out = []
    for m in _DATE_RE.finditer(text):
        if _near_before(text, m.start(), _BIRTH_LABELS, span=12):
            value = m.group(0).rstrip(". \n")
            out.append(Finding("BIRTH", m.start(), m.start() + len(value), value, 0.85, ["생년월일 항목 옆 날짜"]))
    return out


# 주소: 시·도(옛 이름 포함)로 시작하거나, '주소' 항목 옆에서 시·군·구로 시작하는 것
_SIDO = [
    "서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시", "울산광역시",
    "세종특별자치시", "경기도", "강원특별자치도", "강원도", "충청북도", "충청남도", "전북특별자치도",
    "전라북도", "전라남도", "경상북도", "경상남도", "제주특별자치도", "제주도",
    "서울시", "부산시", "대구시", "인천시", "광주시", "대전시", "울산시", "세종시",
    "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "강원", "충북", "충남",
    "전북", "전남", "경북", "경남", "제주",
]
_SIDO_ALT = "|".join(sorted(set(_SIDO), key=len, reverse=True))
_ADDR_UNIT = r"[가-힣0-9]+(?:시|군|구|읍|면|동|리|로|길|가|대로|번길)"
_ADDR_BODY = (
    rf"(?:\s*{_ADDR_UNIT})+"
    r"(?:\s*(?:지하\s*)?\d+(?:-\d+)?(?:번지|번길)?)?"
)
_ADDR_TAIL = re.compile(
    r"(?:\s*,?\s*(?:\d+\s*동\s*)?\d+\s*호"          # 101동 1203호 / 1203호
    r"|\s*,?\s*\d+\s*층"                            # 3층
    r"|\s*,?\s*\d+\s*동(?=\s*\d+\s*호)"
    r"|\s*\([^()\n]{1,40}\)"                        # (인후동, 현대아파트)
    r"|\s*,?\s*[가-힣0-9]{1,15}(?:아파트|빌라|맨션|타운|오피스텔|빌딩|주공|하이츠|캐슬|자이|푸르지오|래미안))+"
)
_ADDR_FULL_RE = re.compile(rf"(?:{_SIDO_ALT})(?=\s){_ADDR_BODY}")
_ADDR_LABELS = ("주소", "주 소", "거주지", "현주소", "주소지", "주민등록상주소", "본적", "등록기준지", "실거주지", "우편물수령지")


def _extend_address(text: str, start: int, end: int) -> int:
    m = _ADDR_TAIL.match(text, end)
    return m.end() if m else end


def _rule_address(text: str) -> list[Finding]:
    out = []
    covered: list[tuple[int, int]] = []
    for m in _ADDR_FULL_RE.finditer(text):
        raw = m.group(0).rstrip()
        # 시·도 뒤에 행정구역·도로명이 최소 하나는 있어야 한다('전북 교육' 같은 말 제외).
        rest = raw[len(re.match(_SIDO_ALT, raw).group(0)):]
        if not re.search(r"(시|군|구|읍|면|동|리|로|길)(\s|$)|\d", rest):
            continue
        start = m.start()
        end = _extend_address(text, start, start + len(raw))
        score = 0.75 + (0.1 if re.search(r"\d", text[start:end]) else 0)
        if _near_before(text, start, _ADDR_LABELS, span=12):
            score += 0.1
        out.append(Finding("ADDRESS", start, end, text[start:end], min(score, 0.95), ["시·도로 시작하는 주소"]))
        covered.append((start, end))
    # 시·도 없이 '전주시 완산구 …' 처럼 쓴 주소는 '주소' 항목 옆일 때만 인정한다.
    local = re.compile(rf"[가-힣]{{1,6}}(?:시|군){_ADDR_BODY}")
    for m in local.finditer(text):
        start = m.start()
        if any(s <= start < e for s, e in covered):
            continue
        if not _near_before(text, start, _ADDR_LABELS, span=12):
            continue
        end = _extend_address(text, start, start + len(m.group(0).rstrip()))
        out.append(Finding("ADDRESS", start, end, text[start:end], 0.8, ["주소 항목 옆 시·군으로 시작하는 주소"]))
    return out


# 이름 앞에 오는 관계·역할 낱말. ko-pii 의 항목 라벨보다 인사·가족 서류 쪽을 넓혔다.
_NAME_CUES = (
    "성명", "성 명", "이름", "이 름", "성함", "본인",
    "후보자", "임용후보자", "합격자", "피징계자", "징계대상자", "출장자", "동행자", "참석자", "위원",
    "배우자", "자녀", "장남", "장녀", "차남", "차녀", "삼남", "삼녀", "아들", "딸",
    "부친", "모친", "부", "모", "父", "母", "조부", "조모", "손자", "손녀", "형제", "자매", "동거인",
    "세대주", "예금주", "수취인", "수령인", "계약자", "임차인", "임대인", "보증인", "보호자", "대리인",
    "신청인", "신청자", "대상자", "응시자", "지원자", "추천인", "피추천인", "담당자", "작성자", "확인자",
    "故",
)
# '성\n명:' 처럼 항목 이름 글자 사이가 벌어지거나 줄이 바뀐 서식(이수증 등)도 받는다.
_SPREAD_CUES = {"성명", "이름", "성함"}
_STRONG_LABELS = {"성명", "성 명", "이름", "이 름", "성함"}


def _cue_pattern(cue: str) -> str:
    if cue in _SPREAD_CUES:
        return r"\s*".join(re.escape(ch) for ch in cue)
    return re.escape(cue)


_CUE_ALT = "|".join(_cue_pattern(c) for c in sorted(_NAME_CUES, key=len, reverse=True))
# 문장 속에서도 흔히 쓰이는 낱말(자녀 양육, 본인 확인 …). 이 뒤의 이름은 이름 뒤가 끊겨 있어야 인정한다.
_WEAK_CUES = {
    "본인", "자녀", "아들", "딸", "부", "모", "형제", "자매", "가족", "담당자", "작성자", "확인자",
    "후보자", "임용후보자", "합격자", "출장자", "동행자", "참석자", "위원", "대상자", "지원자", "응시자",
}
_CUE_RE = re.compile(
    rf"(?:^|(?<=[\s,(:·/]))({_CUE_ALT})(?:\([^()\n]{{1,6}}\))?\)?(?:\s*[:：]\s*|[ \t]+)({_HANGUL_NAME})", re.M
)
# 이름 뒤가 끊긴 모양: 쉼표·괄호·줄바꿈·끝, '외 n인', 숫자, 호칭
_NAME_END_RE = re.compile(r"(?:\s*[,()\n/·;]|\s*$|\s+외\s|\s*[:：]|\s+\d|\s*(?:씨|님)(?:\s|$|[,.]))")
_WEAK_END_RE = re.compile(r"(?:\s*[,()\n/·;]|\s*$|\s+외\s|\s*(?:씨|님)(?:\s|$|[,.]))")
_HANJA_NAME_RE = re.compile(rf"({_HANGUL_NAME})\s?\(([\u3400-\u9fff\uf900-\ufaff가-힣]{{2,4}})\)")
_PARTICLE = "은는이가을를의에과와도만께님씨로"


def _trim_particle(token: str) -> str:
    # '홍길동과' → '홍길동'. 세 글자는 떼지 않는다('이남은' 같은 이름이 있다).
    if len(token) == 4 and token[-1] in _PARTICLE and _looks_like_name(token[:-1]):
        return token[:-1]
    return token


def _rule_person(text: str) -> list[Finding]:
    out = []
    for m in _CUE_RE.finditer(text):
        cue = re.sub(r"\s+", "", m.group(1))
        token = _trim_particle(m.group(2))
        if not _looks_like_name(token):
            continue
        if cue not in {re.sub(r"\s+", "", c) for c in _STRONG_LABELS} and _odd_four(token):
            continue
        start = m.start(2)
        if cue in _WEAK_CUES:
            # 문장 속 낱말일 수 있어 더 엄격하게: 세 글자 이상, 이름 뒤가 끊겨 있거나 호칭이 붙은 것만
            end = start + len(token)
            if len(token) < 3 or _odd_four(token) or not (_WEAK_END_RE.match(text, end) or _TITLE_RE.match(text, end)):
                continue
        out.append(Finding("PERSON", start, start + len(token), token, 0.85, [f"'{cue}' 뒤 이름"]))
    for m in _HANJA_NAME_RE.finditer(text):
        name, hanja = m.group(1), m.group(2)
        if len(name) == len(hanja) and _hanja_surname_ok(name, hanja) and _looks_like_name(name):
            out.append(Finding("PERSON", m.start(), m.end(), m.group(0), 0.9, ["한자를 함께 쓴 이름"]))
    out += _rule_vertical_names(text)
    return out


_COLUMN_NAME_HEADERS = {"성명", "이름", "성함", "성 명", "이 름"}


def _rule_vertical_names(text: str) -> list[Finding]:
    """한글 표가 한 칸씩 세로로 풀려 '성명' 아래로 이름만 줄줄이 이어진 모양."""
    out = []
    lines = text.split("\n")
    pos = 0
    offsets = []
    for line in lines:
        offsets.append(pos)
        pos += len(line) + 1
    i = 0
    while i < len(lines):
        if lines[i].strip() in _COLUMN_NAME_HEADERS:
            j = i + 1
            while j < len(lines) and j - i <= 200:
                token = lines[j].strip()
                if not token:
                    j += 1
                    continue
                if not _looks_like_name(token):
                    break
                start = offsets[j] + lines[j].index(token)
                out.append(Finding("PERSON", start, start + len(token), token, 0.8, ["'성명' 아래 이어진 이름"]))
                j += 1
            i = j
        else:
            i += 1
    return out


def _rule_hanja_extend(text: str, findings: list[Finding]) -> None:
    """ko-pii 가 '김철수' 만 잡은 경우 뒤의 '(金哲洙)' 까지 넓힌다."""
    for f in findings:
        if f.kind != "PERSON":
            continue
        m = re.match(r"\s?\(([\u3400-\u9fff\uf900-\ufaff가-힣]{2,4})\)", text[f.end:])
        if m and len(m.group(1)) == len(f.text) and _hanja_surname_ok(f.text, m.group(1)):
            f.end += m.end()
            f.text = text[f.start:f.end]
            if "한자를 함께 쓴 이름" not in f.reasons:
                f.reasons.append("한자를 함께 쓴 이름")


def _rule_address_extend(text: str, findings: list[Finding]) -> None:
    for f in findings:
        if f.kind == "ADDRESS":
            end = _extend_address(text, f.start, f.end)
            if end > f.end:
                f.end = end
                f.text = text[f.start:f.end]
                if "상세주소까지 포함" not in f.reasons:
                    f.reasons.append("상세주소까지 포함")


def _rule_name_list(text: str, findings: list[Finding]) -> list[Finding]:
    """'권도윤(權度潤), 황보선영, 제갈민' 처럼 이미 찾은 이름에 쉼표로 이어진 이름들."""
    out = []
    persons = [f for f in findings if f.kind == "PERSON" and f.confidence >= 0.8]
    item = re.compile(rf"\s*[,·、]\s*({_HANGUL_NAME})(?:\s?\([^()\n]{{1,6}}\))?")
    for f in persons:
        pos = f.end
        while True:
            m = item.match(text, pos)
            if not m or not _looks_like_name(m.group(1)):
                break
            if not _NAME_END_RE.match(text, m.end(1)) and not text[m.end(1):m.end(1) + 1] == "(":
                break
            out.append(Finding("PERSON", m.start(1), m.end(1), m.group(1), 0.75, ["이름 목록에 이어진 이름"]))
            pos = m.end()
    return out


def _rule_same_name(text: str, findings: list[Finding]) -> list[Finding]:
    """확실하게 찾은 이름이 글 안의 다른 곳에 또 나오면 그 자리도 표시한다."""
    names = {f.text.split("(")[0] for f in findings if f.kind == "PERSON" and f.confidence >= 0.8}
    out = []
    for name in names:
        if len(name) < 2:
            continue
        for m in re.finditer(re.escape(name), text):
            if any(f.kind == "PERSON" and f.start <= m.start() < f.end for f in findings):
                continue
            prev = text[m.start() - 1:m.start()]
            if prev and re.match(r"[가-힣]", prev):
                continue
            out.append(Finding("PERSON", m.start(), m.end(), name, 0.8, ["같은 글에서 이름으로 찾은 낱말"]))
    return out


_RULES = (_rule_rrn, _rule_phone, _rule_card, _rule_account, _rule_biz, _rule_birth, _rule_address, _rule_person)


# ---------------------------------------------------------------- 합치기

# 겹칠 때 누가 이기는지. 숫자가 클수록 먼저.
_PRIORITY = {
    "RRN": 90, "FRN": 90, "CARD": 85, "ACCOUNT": 80, "PASSPORT": 80, "DRIVER": 80,
    "MOBILE": 75, "BIZ": 70, "EMPLOYEE_ID": 65, "PHONE": 60, "EMAIL": 60,
    "ADDRESS": 55, "BIRTH": 50, "VEHICLE": 45, "PERSON": 40, "CUSTOM": 100,
}


def _merge(findings: list[Finding]) -> list[Finding]:
    # 1) 같은 종류가 겹치면 하나로 넓힌다.
    findings = sorted(findings, key=lambda f: (f.start, -f.end))
    merged: list[Finding] = []
    for f in findings:
        same = next((g for g in merged if g.kind == f.kind and f.start < g.end and g.start < f.end), None)
        if same is None:
            merged.append(Finding(f.kind, f.start, f.end, f.text, f.confidence, list(f.reasons)))
            continue
        same.start, same.end = min(same.start, f.start), max(same.end, f.end)
        same.confidence = max(same.confidence, f.confidence)
        for r in f.reasons:
            if r not in same.reasons:
                same.reasons.append(r)
    # 2) 다른 종류가 겹치면 우선순위·신뢰도·길이 순으로 하나만 남긴다.
    ranked = sorted(merged, key=lambda f: (-_PRIORITY.get(f.kind, 0), -f.confidence, -(f.end - f.start)))
    kept: list[Finding] = []
    for f in ranked:
        if any(f.start < k.end and k.start < f.end for k in kept):
            continue
        kept.append(f)
    return sorted(kept, key=lambda f: f.start)


def detect_text(text: str) -> list[Finding]:
    """글 한 덩어리에서 개인정보를 찾는다. 위치(start, end)는 text 기준."""
    if not text or not text.strip():
        return []
    findings = _from_ko_pii(text)
    for rule in _RULES:
        findings += rule(text)
    _rule_hanja_extend(text, findings)
    _rule_address_extend(text, findings)
    findings += _rule_name_list(text, findings)
    findings += _rule_same_name(text, findings)
    result = _merge(findings)
    for f in result:
        f.text = text[f.start:f.end]
    return result


# ---------------------------------------------------------------- 표

# 표 머리글(칸 이름) → 그 열 값의 종류. 띄어쓰기를 지우고 비교한다.
_HEADER_KINDS = {
    "PERSON": ("성명", "이름", "성함", "본인성명", "대상자", "신청인", "예금주", "수령인", "보호자", "보호자성명",
               "배우자", "배우자성명", "자녀", "자녀성명", "가족성명", "성명(한글)", "한글성명"),
    "RRN": ("주민등록번호", "주민번호", "주민등록번호(외국인등록번호)"),
    "FRN": ("외국인등록번호",),
    "BIRTH": ("생년월일", "생일", "출생일"),
    "ADDRESS": ("주소", "현주소", "거주지", "주소지", "주민등록상주소", "실거주지", "본적", "등록기준지"),
    "PHONE": ("연락처", "전화번호", "전화", "휴대폰", "휴대전화", "핸드폰", "휴대폰번호", "비상연락처", "연락처(휴대폰)", "자택전화"),
    "ACCOUNT": ("계좌번호", "계좌", "입금계좌", "급여계좌", "통장번호"),
    "EMAIL": ("이메일", "전자우편", "e-mail", "email", "메일"),
    "VEHICLE": ("차량번호",),
    "EMPLOYEE_ID": ("사번", "직원번호", "개인번호"),
}
_HEADER_LOOKUP = {h.lower(): kind for kind, heads in _HEADER_KINDS.items() for h in heads}
_EMPTY_CELLS = {"", "-", "–", "—", "없음", "해당없음", "해당 없음", "무", "x", "X"}


def _trim_span(value: str) -> tuple[int, int]:
    """칸 글자 앞뒤 빈칸을 뺀 범위."""
    a = len(value) - len(value.lstrip())
    b = len(value.rstrip())
    return a, max(a, b)


def header_kind(cell: str) -> str | None:
    key = re.sub(r"\s+", "", str(cell or "")).lower().rstrip(":：")
    return _HEADER_LOOKUP.get(key)


def _value_fits(kind: str, value: str) -> bool:
    """표 머리글·항목명으로 정한 종류에 값 모양이 맞는지. '자녀 | 1일' 같은 규정 표를 거른다."""
    v = value.strip()
    digits = len(re.sub(r"\D", "", v))
    if kind == "PERSON":
        return bool(re.fullmatch(r"[가-힣]{2,5}(?:\s?\([^()]{1,8}\))?", v)) and v not in _NOT_NAMES \
            and not header_kind(v)
    if kind in ("RRN", "FRN"):
        return bool(re.search(r"\d{6}\s?-?\s?[\d*＊xX●○]", v))
    if kind == "BIRTH":
        return digits >= 4
    if kind == "ADDRESS":
        return bool(re.search(r"[가-힣]", v)) and len(v) >= 4 and bool(
            re.search(r"(시|군|구|읍|면|동|리|로|길|번지|아파트|\d)", v))
    if kind in ("PHONE", "MOBILE"):
        return 7 <= digits <= 12
    if kind == "ACCOUNT":
        return 8 <= digits <= 20
    if kind == "EMAIL":
        return "@" in v
    if kind == "VEHICLE":
        return bool(re.search(r"\d{2,3}\s?[가-힣]\s?\d{4}", v))
    if kind == "EMPLOYEE_ID":
        return bool(re.search(r"[0-9A-Za-z]{3,}", v))
    return True


def _cell_kind(kind: str, value: str) -> str:
    if kind == "PHONE" and re.sub(r"\D", "", value).startswith(("010", "011", "016", "017", "018", "019")):
        return "MOBILE"
    if kind == "RRN" and re.search(r"\d{6}\s?-\s?[5-8]", value):
        return "FRN"
    return kind


@dataclass
class CellFinding:
    row: int
    col: int
    finding: Finding

    def to_dict(self) -> dict:
        d = self.finding.to_dict()
        d.update(row=self.row, col=self.col)
        return d


def detect_table(rows: list[list[Optional[str]]]) -> list[CellFinding]:
    """표(행 × 칸 글자)에서 개인정보를 찾는다.

    - 머리글 줄: '성명·주민등록번호·주소 …' 칸이 있는 줄 아래로 그 열의 값 전체를 해당 종류로 본다.
      값 모양만으로는 판단이 안 되는 명부·대장의 이름·주소를 놓치지 않기 위해서다.
    - 항목-값 짝: 한 줄에 '성명 | 홍길동 | 생년월일 | 1978.3.2' 처럼 항목 칸 바로 옆 칸이 값인 서식.
    - 그 밖의 칸도 글 한 덩어리로 보고 detect_text 로 찾는다.
    - 칸 값이 None 이면 병합으로 가려진 칸이다. 한 줄을 칸 하나가 통째로 차지한 줄(안내문·소제목)은
      머리글 열의 값으로 보지 않고, 그 글이 길면(문장) 표의 다른 부분이 시작된 것으로 보고 머리글 열을 끝낸다.
      서식 한 장에 '대상자·성명' 칸 아래로 '동의자', '유의사항' 같은 글이 이어지는 경우를 이름으로 잡지 않기 위해서다.
    """
    found: dict[tuple[int, int, int, int], CellFinding] = {}

    def add(r: int, c: int, f: Finding) -> None:
        key = (r, c, f.start, f.end)
        old = found.get(key)
        if old is None or _PRIORITY.get(f.kind, 0) > _PRIORITY.get(old.finding.kind, 0):
            found[key] = CellFinding(r, c, f)

    columns: dict[int, tuple[str, str]] = {}   # 열 번호 → (종류, 머리글)
    for r, row in enumerate(rows):
        cells = [str(v or "") for v in row]
        present = [c for c, v in enumerate(row) if v is not None]
        full_width = len(row) > 1 and len(present) == 1
        if full_width and len(cells[present[0]].strip()) >= 20:
            columns = {}
        kinds = [header_kind(v) for v in cells]
        header_hits = sum(1 for k in kinds if k)
        # 머리글 줄: 항목 칸이 둘 이상이고, 나머지 칸에 값(숫자·@·개인정보로 보이는 글)이 없는 줄.
        # '주소 | 군산시 대학로 558 | 이메일 | …' 같은 항목-값 짝 줄을 머리글로 오해하지 않게 한다.
        is_header_row = header_hits >= 2 and not any(
            (not kinds[c]) and v.strip() and (re.search(r"[\d@]", v) or detect_text(v))
            for c, v in enumerate(cells)
        )
        if is_header_row:
            columns = {c: (k, cells[c].strip()) for c, k in enumerate(kinds) if k}
            continue
        # 항목-값 짝
        pair_cols = set()
        for c, k in enumerate(kinds):
            if k and c + 1 < len(cells) and not header_kind(cells[c + 1]):
                value = cells[c + 1].strip()
                if value in _EMPTY_CELLS or not _value_fits(k, value):
                    continue
                kind = _cell_kind(k, value)
                a, b = _trim_span(cells[c + 1])
                f = Finding(kind, a, b, cells[c + 1][a:b], 0.9, [f"'{cells[c].strip()}' 칸 옆 값"])
                add(r, c + 1, f)
                pair_cols.add(c + 1)
        # 머리글 아래 열 값(한 줄을 통째로 차지한 칸은 열 값이 아니다)
        for c, (k, head) in columns.items():
            if full_width or c in pair_cols or c >= len(cells) or kinds[c]:
                continue
            value = cells[c].strip()
            if value in _EMPTY_CELLS or not _value_fits(k, value):
                continue
            kind = _cell_kind(k, value)
            a, b = _trim_span(cells[c])
            add(r, c, Finding(kind, a, b, cells[c][a:b], 0.9, [f"'{head}' 열"]))
        # 모든 칸 글 검사(다른 종류가 섞여 있을 수 있음)
        for c, value in enumerate(cells):
            if kinds[c]:
                continue
            for f in detect_text(value):
                if any(cf.row == r and cf.col == c and cf.finding.start <= f.start and f.end <= cf.finding.end
                       for cf in found.values()):
                    continue
                add(r, c, f)
    return sorted(found.values(), key=lambda cf: (cf.row, cf.col, cf.finding.start))
