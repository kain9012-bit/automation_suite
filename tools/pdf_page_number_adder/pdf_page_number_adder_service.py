from __future__ import annotations

import io
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


def get_pdf_page_count(pdf_path: str | Path) -> int:
    reader = PdfReader(str(pdf_path))
    return len(reader.pages)


def format_preview_text(number: int, total_pages: int, format_type: str) -> str:
    if format_type == "1":
        return f"{number}"
    if format_type == "01":
        return f"{number:02d}"
    if format_type == "001":
        return f"{number:03d}"
    if format_type == "- 1 -":
        return f"- {number} -"
    if format_type == "1쪽":
        return f"{number}쪽"
    if format_type == "1페이지":
        return f"{number}페이지"
    if format_type == "1 / 전체페이지수":
        return f"{number} / {total_pages}"
    return f"{number}"


def _find_korean_font_path() -> Path | None:
    candidates = [
        Path("C:/Windows/Fonts/gulim.ttc"),
        Path("C:/Windows/Fonts/gulim.ttf"),
        Path("C:/Windows/Fonts/malgun.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def _register_font() -> str:
    font_path = _find_korean_font_path()
    if font_path is None:
        return "Helvetica"

    font_name = "PdfPageNumberFont"
    try:
        pdfmetrics.getFont(font_name)
        return font_name
    except Exception:
        pass

    pdfmetrics.registerFont(TTFont(font_name, str(font_path)))
    return font_name


def _calc_position(
    page_width: float,
    page_height: float,
    text: str,
    position: str,
    font_name: str,
    font_size: int,
) -> tuple[float, float]:
    text_width = pdfmetrics.stringWidth(text, font_name, font_size)

    margin_x = 28
    margin_y = 20

    if position == "좌상단":
        x = margin_x
        y = page_height - margin_y - font_size
    elif position == "상단 중앙":
        x = (page_width - text_width) / 2
        y = page_height - margin_y - font_size
    elif position == "우상단":
        x = page_width - margin_x - text_width
        y = page_height - margin_y - font_size
    elif position == "좌하단":
        x = margin_x
        y = margin_y
    elif position == "하단 중앙":
        x = (page_width - text_width) / 2
        y = margin_y
    elif position == "우하단":
        x = page_width - margin_x - text_width
        y = margin_y
    else:
        x = (page_width - text_width) / 2
        y = margin_y

    return x, y


def _make_overlay_page(
    page_width: float,
    page_height: float,
    text: str,
    position: str,
    font_size: int,
):
    packet = io.BytesIO()
    c = canvas.Canvas(packet, pagesize=(page_width, page_height))

    font_name = _register_font()
    c.setFont(font_name, font_size)

    x, y = _calc_position(
        page_width=page_width,
        page_height=page_height,
        text=text,
        position=position,
        font_name=font_name,
        font_size=font_size,
    )

    # 딱 한 번만 그림
    c.drawString(x, y, text)
    c.save()

    packet.seek(0)
    overlay_reader = PdfReader(packet)
    return overlay_reader.pages[0]


def build_output_path(input_pdf: str | Path) -> Path:
    input_path = Path(input_pdf).resolve()
    parent = input_path.parent
    stem = input_path.stem
    suffix = input_path.suffix

    candidate = parent / f"{stem}_페이지번호추가{suffix}"
    if not candidate.exists():
        return candidate

    idx = 1
    while True:
        candidate = parent / f"{stem}_페이지번호추가({idx}){suffix}"
        if not candidate.exists():
            return candidate
        idx += 1


def add_page_numbers(
    input_pdf: str | Path,
    output_pdf: str | Path,
    format_type: str,
    start_page: int,
    start_number: int,
    position: str,
    font_name: str = "굴림체",
    font_size: int = 10,
) -> Path:
    input_path = Path(input_pdf).resolve()
    output_path = Path(output_pdf).resolve()

    reader = PdfReader(str(input_path))
    writer = PdfWriter()

    total_pages = len(reader.pages)
    current_number = start_number

    for page_index, src_page in enumerate(reader.pages, start=1):
        page = src_page

        if page_index >= start_page:
            page_width = float(page.mediabox.width)
            page_height = float(page.mediabox.height)

            text = format_preview_text(
                number=current_number,
                total_pages=total_pages,
                format_type=format_type,
            )

            overlay_page = _make_overlay_page(
                page_width=page_width,
                page_height=page_height,
                text=text,
                position=position,
                font_size=font_size,
            )

            # 선택한 형식/위치 1회만 병합
            page.merge_page(overlay_page)
            current_number += 1

        writer.add_page(page)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        writer.write(f)

    return output_path