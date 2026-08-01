"""이수증 PDF 공통 파서·파일명 유틸리티.

cert_app / certificate_pdf_renamer / certificate_pdf_splitter_app 세 도구가
동일하게 사용하던 기관 판별·텍스트 파싱·파일명 정리 로직을 한 곳으로 통합한 모듈.
(CORE_RULES §4 중복 구현 방지)

원본 세 스크립트의 함수 시그니처와 동작을 그대로 보존한다.
"""

from __future__ import annotations

import re
from pathlib import Path


# ==========================================================
# 기관 판별
# ==========================================================

def detect_org(text: str) -> str:
    """이수증 텍스트에서 연수기관을 판별해 코드로 반환.

    JBEDU   : 전북특별자치도교육청교육연수원
    JBFUT   : 전북특별자치도교육청미래교육연구원
    CENTR   : 중앙교육연수원
    STAT    : 통계인재개발원
    PEACE   : 국립평화통일민주교육원
    UNKNOWN : 알 수 없음 (기본 MOE 양식으로 파싱)
    """
    if "통계인재개발원" in text:
        return "STAT"

    if "국립평화통일민주교육원" in text:
        return "PEACE"
    if "교육인정시간" in text and re.search(r"[0-9]{4}-CES[0-9]+-[0-9]+", text):
        return "PEACE"

    if "전북교연" in text:
        return "JBEDU"
    if "전북미연" in text:
        return "JBFUT"
    if "중앙교육연수원" in text:
        return "CENTR"

    return "UNKNOWN"


ORG_NAME_MAP = {
    "JBEDU": "전북특별자치도교육청교육연수원",
    "JBFUT": "전북특별자치도교육청미래교육연구원",
    "CENTR": "중앙교육연수원",
    "STAT": "통계인재개발원",
    "PEACE": "국립평화통일민주교육원",
}


# ==========================================================
# 공통 파싱 함수
# ==========================================================

def split_lines(text: str):
    return [line.strip() for line in text.splitlines() if line and line.strip()]


def parse_moe_style(text: str) -> dict:
    """전북교연 / 전북미연 / 중앙교육연수원 등 교육부 계열 이수증 파서.

    주요 구조: 근무기관, 직급, 성명, 생년월일, 연수종류, 이수시간, 과정명, 연수기간, 연수번호
    """
    lines = split_lines(text)

    def is_label_line(line: str) -> bool:
        norm = line.replace(" ", "")
        label_keys = [
            "근무기관:", "근무기관",
            "직급:", "직급",
            "성명:", "성명",
            "생년월일:", "생년월일",
            "연수종류:", "연수종류",
            "과정명:", "과정명",
            "연수기간:", "연수기간",
            "이수시간:", "이수시간",
        ]
        return any(norm.startswith(k) for k in label_keys)

    def get_value_same_or_next(label_keywords):
        for i, line in enumerate(lines):
            norm = line.replace(" ", "")
            if any(norm.startswith(k) for k in label_keywords):
                for sep in [":", "："]:
                    if sep in line:
                        value = line.split(sep, 1)[1].strip()
                        if value:
                            return value

                for j in range(i + 1, len(lines)):
                    candidate = lines[j].strip()
                    if not candidate:
                        continue
                    if is_label_line(candidate):
                        break
                    return candidate

        return ""

    def get_multiline_value(label_keywords):
        for i, line in enumerate(lines):
            norm = line.replace(" ", "")
            if any(norm.startswith(k) for k in label_keywords):
                parts = []

                first_value = ""
                for sep in [":", "："]:
                    if sep in line:
                        first_value = line.split(sep, 1)[1].strip()
                        break

                if first_value:
                    parts.append(first_value)

                for j in range(i + 1, len(lines)):
                    candidate = lines[j].strip()
                    if not candidate:
                        continue
                    if is_label_line(candidate):
                        break
                    parts.append(candidate)

                return "".join(parts).strip()

        return ""

    def get_course_name():
        result_parts = []
        capture = False

        for line in lines:
            norm = line.replace(" ", "")

            if not capture and any(norm.startswith(k) for k in ["과정명:", "과정명"]):
                capture = True
                value = ""
                for sep in [":", "："]:
                    if sep in line:
                        value = line.split(sep, 1)[1].strip()
                        break
                if value:
                    result_parts.append(value)
                continue

            if capture:
                if is_label_line(line):
                    break
                result_parts.append(line.strip())

        return " ".join(result_parts).strip()

    근무기관 = get_multiline_value(["근무기관"])
    if not 근무기관:
        근무기관 = get_value_same_or_next(["근무기관"])

    직급 = get_value_same_or_next(["직급"])
    성명 = get_value_same_or_next(["성명", "성 명"])
    생년월일 = get_value_same_or_next(["생년월일", "생 년 월 일"])
    연수종류 = get_value_same_or_next(["연수종류", "연 수 종 류"])
    과정명 = get_course_name()
    연수기간 = get_value_same_or_next(["연수기간", "연 수 기 간"])

    총이수시간 = ""
    m_total = re.search(r"이\s*수\s*시\s*간\s*:\s*([0-9]+)\s*시간", text)
    if m_total:
        총이수시간 = m_total.group(1).strip()

    연수번호 = ""
    m_cert = re.search(r"(제\s*[^\n]+?호)", text)
    if m_cert:
        연수번호 = m_cert.group(1).strip()

    return {
        "근무기관": 근무기관,
        "직급": 직급,
        "성명": 성명,
        "생년월일": 생년월일,
        "연수종류": 연수종류,
        "과정명": 과정명,
        "총이수시간(시간)": 총이수시간,
        "연수기간": 연수기간,
        "연수번호": 연수번호,
    }


def parse_statdev_style(text: str) -> dict:
    """통계인재개발원 수료증 파서."""

    def find_after(pattern: str):
        m = re.search(pattern, text)
        return m.group(1).strip() if m else ""

    연수번호 = ""
    m_cert = re.search(r"(제\s*[A-Za-z0-9]+\s*호)", text)
    if m_cert:
        연수번호 = m_cert.group(1).strip()

    성명 = find_after(r"성\s*명\s*:\s*([^\n]+)")
    소속 = find_after(r"소\s*속\s*:\s*([^\n]+)")
    교육과정 = find_after(r"교육과정\s*:\s*([^\n]+)")
    교육기간_raw = find_after(r"교육기간\s*:\s*([^\n]+)")

    연수기간 = 교육기간_raw
    총이수시간 = ""
    if 교육기간_raw:
        m_time = re.search(r"\((\d+)\s*시간\)", 교육기간_raw)
        if m_time:
            총이수시간 = m_time.group(1).strip()
        연수기간 = 교육기간_raw.split("(")[0].strip()

    return {
        "근무기관": 소속,
        "직급": "",
        "성명": 성명,
        "생년월일": "",
        "연수종류": "",
        "과정명": 교육과정,
        "총이수시간(시간)": 총이수시간,
        "연수기간": 연수기간,
        "연수번호": 연수번호,
    }


def parse_peace_style(text: str) -> dict:
    """국립평화통일민주교육원 이수증 파서."""

    def find_after(pattern: str):
        m = re.search(pattern, text)
        return m.group(1).strip() if m else ""

    연수번호 = ""
    m_cert = re.search(r"([0-9]{4}-[A-Za-z0-9]+-[0-9]+)", text)
    if m_cert:
        연수번호 = m_cert.group(1).strip()

    근무기관 = find_after(r"소\s*속\s*:\s*([^\n]+)")
    직급 = find_after(r"직\s*급\s*:\s*([^\n]+)")
    성명 = find_after(r"성\s*명\s*:\s*([^\n]+)")
    과정명 = find_after(r"과\s*정\s*:\s*([^\n]+)")
    연수기간 = find_after(r"기\s*간\s*:\s*([^\n]+)")

    총이수시간 = ""
    m_time = re.search(r"교육인정시간\s*:\s*([0-9]+)\s*시간", text)
    if m_time:
        총이수시간 = m_time.group(1).strip()

    return {
        "근무기관": 근무기관,
        "직급": 직급,
        "성명": 성명,
        "생년월일": "",
        "연수종류": "",
        "과정명": 과정명,
        "총이수시간(시간)": 총이수시간,
        "연수기간": 연수기간,
        "연수번호": 연수번호,
    }


def extract_info_from_text(text: str) -> dict:
    org_code = detect_org(text)

    if org_code == "STAT":
        info = parse_statdev_style(text)
    elif org_code == "PEACE":
        info = parse_peace_style(text)
    else:
        info = parse_moe_style(text)

    info["연수기관명"] = ORG_NAME_MAP.get(org_code, "")
    return info


# ==========================================================
# 파일명 유틸리티
# ==========================================================

FILENAME_FIELDS = [
    "과정명",
    "성명",
    "근무기관",
    "직급",
    "생년월일",
    "연수종류",
    "총이수시간(시간)",
    "연수기간",
    "연수번호",
    "연수기관명",
]

DEFAULT_FILENAME_FIELDS = ["과정명", "성명", "근무기관"]

INVALID_FILENAME_CHARS = r'<>:"/\\|?*'


def safe_filename_part(value, max_len=80) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)

    for ch in INVALID_FILENAME_CHARS:
        text = text.replace(ch, " ")

    text = re.sub(r"[\x00-\x1f]", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .")

    if len(text) > max_len:
        text = text[:max_len].rstrip(" .")

    return text


def safe_stem(value, fallback="확인필요") -> str:
    text = safe_filename_part(value, max_len=160)
    return text if text else fallback


def build_output_stem(info: dict, selected_fields: list, delimiter: str) -> str:
    parts = []

    for field in selected_fields:
        value = safe_filename_part(info.get(field, ""))
        if value:
            parts.append(value)

    stem = delimiter.join(parts)
    return safe_stem(stem, fallback="이수증")


def trim_filename(stem: str, max_len=180) -> str:
    stem = safe_stem(stem, fallback="이수증")
    if len(stem) <= max_len:
        return stem
    return stem[:max_len].rstrip(" .")


def unique_path(path, original_path=None) -> Path:
    """같은 파일명이 있으면 (1), (2)를 붙인다.

    original_path가 주어지고 목표 경로가 그 원본과 동일하면 원본 경로를 그대로
    반환한다(renamer에서 '변경 없음' 판정용). splitter/collector는 original_path를
    넘기지 않으므로 기존 단순 동작과 동일하게 작동한다.
    """
    path = Path(path)

    if original_path is not None:
        original_path = Path(original_path)
        try:
            if path.resolve() == original_path.resolve():
                return path
        except Exception:
            if str(path).lower() == str(original_path).lower():
                return path

    if not path.exists():
        return path

    parent = path.parent
    stem = path.stem
    suffix = path.suffix

    n = 1
    while True:
        candidate = parent / f"{stem}({n}){suffix}"

        if original_path is not None:
            try:
                if candidate.resolve() == original_path.resolve():
                    return candidate
            except Exception:
                pass

        if not candidate.exists():
            return candidate

        n += 1


SUPPORTED_ORGS_TEXT = (
    "[지원 연수기관]\n\n"
    "· 전북특별자치도교육청교육연수원\n"
    "· 전북특별자치도교육청미래교육연구원\n"
    "· 중앙교육연수원\n"
    "· 통계인재개발원\n"
    "· 국립평화통일민주교육원\n\n"
    "※ 위 기관 이수증은 구조를 분석해 최적화해 두었습니다.\n"
    "※ 다른 형식의 이수증은 일부 항목이 비어 '확인필요'로 분류될 수 있습니다."
)
