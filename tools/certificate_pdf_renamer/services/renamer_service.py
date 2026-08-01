"""이수증 PDF 파일명 일괄 변경 서비스.

원본: certificate_pdf_renamer/certificate_pdf_renamer_app.py 의 파일명 변경 로직.
1장짜리 이수증 PDF의 파일명을 이수증 정보로 자동 변경한다.

주의: 이 도구는 사용자가 명시적으로 선택한 '파일명 변경'이 본래 목적이므로 원본
파일명을 실제로 바꾼다. UI에서 실행 전 확인 대화상자를 띄우고, 충돌 시 (1),(2)
자동 개명하며, 변경 전후 내역을 엑셀로 남긴다. (CORE_RULES §1 준수)
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pdfplumber
import pandas as pd

from .certificate_parser import (
    extract_info_from_text,
    build_output_stem,
    trim_filename,
    unique_path,
)


def extract_text_and_page_count(pdf_path: Path):
    with pdfplumber.open(pdf_path) as pdf:
        texts = []
        for page in pdf.pages:
            texts.append(page.extract_text() or "")
        return "\n".join(texts), len(pdf.pages)


def save_log_excel(records: list, output_dir: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"이수증_파일명변경결과_{timestamp}.xlsx"

    columns = [
        "상태",
        "누락필드",
        "기존파일명",
        "변경파일명",
        "기존경로",
        "변경경로",
        "페이지수",
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
        "에러메시지",
    ]

    df = pd.DataFrame(records)

    if df.empty:
        df = pd.DataFrame(columns=columns)
    else:
        for col in columns:
            if col not in df.columns:
                df[col] = ""
        df = df[columns]

    changed_df = df[df["상태"] == "변경완료"].copy()
    unchanged_df = df[df["상태"] == "변경없음"].copy()
    check_df = df[df["상태"] == "확인필요"].copy()
    error_df = df[df["상태"] == "에러"].copy()

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        if not changed_df.empty:
            changed_df.to_excel(writer, index=False, sheet_name="변경완료")
        if not unchanged_df.empty:
            unchanged_df.to_excel(writer, index=False, sheet_name="변경없음")
        if not check_df.empty:
            check_df.to_excel(writer, index=False, sheet_name="확인필요")
        if not error_df.empty:
            error_df.to_excel(writer, index=False, sheet_name="에러")

        df.to_excel(writer, index=False, sheet_name="전체")

        for sheet in writer.sheets.values():
            sheet.freeze_panes = "A2"

            for column_cells in sheet.columns:
                max_length = 0
                column_letter = column_cells[0].column_letter

                for cell in column_cells:
                    value = str(cell.value or "")
                    max_length = max(max_length, min(len(value), 60))

                sheet.column_dimensions[column_letter].width = max(max_length + 2, 12)

    return output_path


def rename_certificate_pdfs(
    pdf_files: list,
    selected_fields: list,
    delimiter: str = "_",
    progress_callback=None,
    cancel_event=None,
) -> dict:
    if not pdf_files:
        raise ValueError("선택된 PDF 파일이 없습니다.")

    if not selected_fields:
        raise ValueError("파일명에 사용할 항목을 1개 이상 선택해야 합니다.")

    output_dir = Path(pdf_files[0]).parent
    records = []

    count_changed = 0
    count_unchanged = 0
    count_check = 0
    count_error = 0

    total = len(pdf_files)
    cancelled = False

    for idx, pdf_path in enumerate(pdf_files, start=1):
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
            break

        pdf_path = Path(pdf_path)
        original_path = pdf_path
        original_name = pdf_path.name

        info = {}
        page_count = ""
        status = ""
        missing = []
        error_message = ""
        new_path = ""

        try:
            text, page_count = extract_text_and_page_count(pdf_path)

            if page_count != 1:
                status = "확인필요"
                error_message = "1장짜리 이수증 PDF가 아니어서 파일명을 변경하지 않았습니다."
                count_check += 1

            else:
                info = extract_info_from_text(text)

                missing = [
                    field
                    for field in selected_fields
                    if not str(info.get(field, "")).strip()
                ]

                if missing:
                    status = "확인필요"
                    error_message = "파일명 구성에 필요한 항목이 누락되어 파일명을 변경하지 않았습니다."
                    count_check += 1

                else:
                    base_stem = build_output_stem(info, selected_fields, delimiter)
                    base_stem = trim_filename(base_stem)
                    target_path = unique_path(
                        pdf_path.with_name(f"{base_stem}.pdf"),
                        original_path=pdf_path,
                    )

                    try:
                        same_path = target_path.resolve() == pdf_path.resolve()
                    except Exception:
                        same_path = str(target_path).lower() == str(pdf_path).lower()

                    if same_path:
                        status = "변경없음"
                        new_path = pdf_path
                        count_unchanged += 1
                    else:
                        pdf_path.rename(target_path)
                        status = "변경완료"
                        new_path = target_path
                        count_changed += 1

        except Exception as e:
            status = "에러"
            error_message = str(e)
            count_error += 1

        record = {
            "상태": status,
            "누락필드": ", ".join(missing),
            "기존파일명": original_name,
            "변경파일명": Path(new_path).name if new_path else "",
            "기존경로": str(original_path),
            "변경경로": str(new_path) if new_path else "",
            "페이지수": page_count,
            "에러메시지": error_message,
        }
        record.update(info)
        records.append(record)

        if progress_callback:
            progress_callback(idx, total, f"처리 중: {original_name}")

    log_path = save_log_excel(records, output_dir)

    return {
        "log_path": log_path,
        "changed": count_changed,
        "unchanged": count_unchanged,
        "check": count_check,
        "error": count_error,
        "total": len(records),
        "cancelled": cancelled,
    }
