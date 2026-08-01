from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pandas as pd
import pdfplumber


def detect_org(text: str) -> str:
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


def split_lines(text: str):
    return [line.strip() for line in text.splitlines() if line and line.strip()]


def parse_moe_style(text: str) -> dict:
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

    근무기관 = get_multiline_value(["근무기관"]) or get_value_same_or_next(["근무기관"])
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


def process_pdfs(pdf_files: list[Path]):
    if not pdf_files:
        raise ValueError("선택된 PDF 파일이 없습니다.")

    good_records = []
    bad_records = []
    error_records = []

    required_fields = ["근무기관", "성명", "과정명", "연수번호"]

    for pdf_path in pdf_files:
        try:
            with pdfplumber.open(pdf_path) as pdf:
                texts = []
                for page in pdf.pages:
                    page_text = page.extract_text() or ""
                    texts.append(page_text)
                full_text = "\n".join(texts)

            info = extract_info_from_text(full_text)
            info["파일명"] = pdf_path.name

            missing = [f for f in required_fields if not str(info.get(f, "")).strip()]
            if missing:
                info["상태"] = "확인필요"
                info["누락필드"] = ", ".join(missing)
                bad_records.append(info)
            else:
                info["상태"] = "정상"
                info["누락필드"] = ""
                good_records.append(info)

        except Exception as e:
            error_records.append({"파일명": pdf_path.name, "에러메시지": str(e)})

    df_good = pd.DataFrame(good_records)
    df_bad = pd.DataFrame(bad_records)
    df_error = pd.DataFrame(error_records)

    return df_good, df_bad, df_error


def build_output_path(base_dir: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return base_dir / f"교육이수실적_취합_{timestamp}.xlsx"


def save_result_excel(output_path: Path, df_good, df_bad, df_error):
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        if not df_good.empty:
            df_good.to_excel(writer, index=False, sheet_name="정상")
        if not df_bad.empty:
            df_bad.to_excel(writer, index=False, sheet_name="확인필요")
        if not df_error.empty:
            df_error.to_excel(writer, index=False, sheet_name="에러")