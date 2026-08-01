"""이수증 PDF 자동 분리 서비스.

원본: certificate_pdf_splitter_app/certificate_pdf_splitter_app.py 의 분리 로직.
여러 이수증이 든 PDF를 1장씩 분리하고, 추출 항목으로 파일명을 자동 생성한다.
정상/확인필요/에러 폴더로 분류하고 처리 결과를 엑셀로 저장한다.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pdfplumber
import pandas as pd

try:
    from pypdf import PdfReader, PdfWriter
except ImportError:
    try:
        from PyPDF2 import PdfReader, PdfWriter
    except ImportError:
        PdfReader = None
        PdfWriter = None

from .certificate_parser import (
    extract_info_from_text,
    safe_stem,
    build_output_stem,
    trim_filename,
    unique_path,
)


def write_single_page(reader, page_index: int, output_path: Path):
    writer = PdfWriter()
    writer.add_page(reader.pages[page_index])

    with open(output_path, "wb") as f:
        writer.write(f)


def save_log_excel(records: list, output_dir: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"이수증_분리결과_{timestamp}.xlsx"

    columns = [
        "상태",
        "누락필드",
        "원본파일명",
        "원본페이지",
        "분리파일명",
        "저장경로",
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

    normal_df = df[df["상태"] == "정상"].copy()
    check_df = df[df["상태"] == "확인필요"].copy()
    error_df = df[df["상태"] == "에러"].copy()

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        if not normal_df.empty:
            normal_df.to_excel(writer, index=False, sheet_name="정상")
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
                    if len(value) > max_length:
                        max_length = min(len(value), 60)

                sheet.column_dimensions[column_letter].width = max(max_length + 2, 12)

    return output_path


def split_certificate_pdfs(
    pdf_files: list,
    output_root: Path,
    selected_fields: list,
    delimiter: str = "_",
    progress_callback=None,
    cancel_event=None,
) -> dict:
    if PdfReader is None or PdfWriter is None:
        raise RuntimeError(
            "pypdf 또는 PyPDF2가 설치되어 있지 않습니다.\n\n"
            "명령프롬프트에서 다음 명령을 실행하세요.\n"
            "py -m pip install pypdf"
        )

    if not pdf_files:
        raise ValueError("선택된 PDF 파일이 없습니다.")

    if not selected_fields:
        raise ValueError("파일명에 사용할 항목을 1개 이상 선택해야 합니다.")

    output_root = Path(output_root)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = output_root / f"이수증_분리_{timestamp}"

    normal_dir = run_dir / "정상"
    check_dir = run_dir / "확인필요"
    error_dir = run_dir / "에러"

    normal_dir.mkdir(parents=True, exist_ok=True)
    check_dir.mkdir(parents=True, exist_ok=True)
    error_dir.mkdir(parents=True, exist_ok=True)

    total_pages = 0
    for pdf_path in pdf_files:
        try:
            total_pages += len(PdfReader(str(pdf_path)).pages)
        except Exception:
            total_pages += 1

    records = []
    count_normal = 0
    count_check = 0
    count_error = 0
    done = 0
    cancelled = False

    for pdf_path in pdf_files:
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
            break

        pdf_path = Path(pdf_path)

        try:
            reader = PdfReader(str(pdf_path))
            page_count = len(reader.pages)
        except Exception as e:
            count_error += 1
            records.append({
                "상태": "에러",
                "원본파일명": pdf_path.name,
                "원본페이지": "",
                "에러메시지": f"PDF 열기 실패: {e}",
            })

            done += 1
            if progress_callback:
                progress_callback(done, total_pages, f"PDF 열기 실패: {pdf_path.name}")

            continue

        try:
            plumber_pdf = pdfplumber.open(pdf_path)
        except Exception as e:
            plumber_pdf = None
            count_error += 1
            records.append({
                "상태": "에러",
                "원본파일명": pdf_path.name,
                "원본페이지": "",
                "에러메시지": f"텍스트 추출용 PDF 열기 실패: {e}",
            })

        for page_index in range(page_count):
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                break

            done += 1

            info = {}
            status = ""
            missing = []
            output_path = ""
            error_message = ""

            try:
                page_text = ""
                if plumber_pdf is not None and page_index < len(plumber_pdf.pages):
                    page_text = plumber_pdf.pages[page_index].extract_text() or ""

                info = extract_info_from_text(page_text)
                missing = [
                    field
                    for field in selected_fields
                    if not str(info.get(field, "")).strip()
                ]

                if missing:
                    status = "확인필요"
                    target_dir = check_dir
                    base_stem = f"확인필요_{safe_stem(pdf_path.stem)}"
                    count_check += 1
                else:
                    status = "정상"
                    target_dir = normal_dir
                    base_stem = build_output_stem(info, selected_fields, delimiter)
                    count_normal += 1

                base_stem = trim_filename(base_stem)
                output_path = unique_path(target_dir / f"{base_stem}.pdf")
                write_single_page(reader, page_index, output_path)

            except Exception as e:
                status = "에러"
                error_message = str(e)
                count_error += 1

                try:
                    base_stem = f"에러_{safe_stem(pdf_path.stem)}"
                    output_path = unique_path(error_dir / f"{trim_filename(base_stem)}.pdf")
                    write_single_page(reader, page_index, output_path)
                except Exception:
                    output_path = ""

            record = {
                "상태": status,
                "누락필드": ", ".join(missing),
                "원본파일명": pdf_path.name,
                "원본페이지": page_index + 1,
                "분리파일명": Path(output_path).name if output_path else "",
                "저장경로": str(output_path) if output_path else "",
                "에러메시지": error_message,
            }
            record.update(info)
            records.append(record)

            if progress_callback:
                progress_callback(
                    done,
                    total_pages,
                    f"처리 중: {pdf_path.name} / {page_index + 1}쪽",
                )

        if plumber_pdf is not None:
            plumber_pdf.close()

        if cancelled:
            break

    log_path = save_log_excel(records, run_dir)

    return {
        "run_dir": run_dir,
        "normal_dir": normal_dir,
        "check_dir": check_dir,
        "error_dir": error_dir,
        "log_path": log_path,
        "normal": count_normal,
        "check": count_check,
        "error": count_error,
        "total": len(records),
        "cancelled": cancelled,
    }
