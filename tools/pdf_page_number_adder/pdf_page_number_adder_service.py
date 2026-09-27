from __future__ import annotations

import io
import logging
import re
from pathlib import Path

from pypdf import PdfReader, PdfWriter, Transformation
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

# pypdf 는 손상된 PDF 경고("EOF marker not found" 등)를 stderr 로 찍는다.
# 앱은 실패할 때 stderr 를 그대로 오류 창에 띄우므로 영어 경고가 섞이지 않게 줄인다.
logging.getLogger("pypdf").setLevel(logging.ERROR)

# 앱 화면(toolSchemas.ts)은 '숫자', '하단 가운데' 같은 이름을 보낸다.
# 예전 화면(PySide6)이 쓰던 '1', '하단 중앙' 도 그대로 받는다.
FORMAT_ALIASES = {
    "숫자": "1",
    "-숫자-": "- 1 -",
    "숫자/전체": "1 / 전체페이지수",
    "숫자/전체페이지수": "1 / 전체페이지수",
}
POSITION_ALIASES = {
    "상단왼쪽": "좌상단",
    "상단가운데": "상단 중앙",
    "상단중앙": "상단 중앙",
    "상단오른쪽": "우상단",
    "하단왼쪽": "좌하단",
    "하단가운데": "하단 중앙",
    "하단중앙": "하단 중앙",
    "하단오른쪽": "우하단",
    "좌상단": "좌상단",
    "우상단": "우상단",
    "좌하단": "좌하단",
    "우하단": "우하단",
}


def normalize_format(format_type: str) -> str:
    value = str(format_type or "").strip()
    return FORMAT_ALIASES.get(re.sub(r"\s+", "", value), value)


def normalize_position(position: str) -> str:
    value = str(position or "").strip()
    return POSITION_ALIASES.get(re.sub(r"\s+", "", value), value)


def describe_pdf_error(error: BaseException) -> str:
    """PDF 라이브러리의 영어 오류를 짧은 한국어 사유로 바꾼다. 파일 이름은 부르는 쪽이 붙인다."""
    text = str(error).strip()
    probe = f"{type(error).__name__} {text} {error!r}".lower()
    if any(key in probe for key in ("decrypt", "encrypt", "password")):
        return "암호가 걸린 PDF라 열 수 없습니다. 암호를 해제한 뒤 다시 시도하세요."
    if any(key in probe for key in (
        "failed to open", "eof", "startxref", "xref", "stream has ended",
        "invalid pdf header", "/root", "trailer", "pdfreaderror", "pdfstreamerror",
        "filedataerror", "emptyfileerror", "pdfsyntaxerror", "pdfminer", "not a pdf",
    )):
        return "PDF 파일이 손상되었거나 PDF 형식이 아닙니다."
    if re.search(r"[가-힣]", text):
        return text
    return f"처리하지 못했습니다. ({text or type(error).__name__})"


def get_pdf_page_count(pdf_path: str | Path) -> int:
    reader = PdfReader(str(pdf_path))
    return len(reader.pages)


def format_preview_text(number: int, total_pages: int, format_type: str) -> str:
    format_type = normalize_format(format_type)
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
    position = normalize_position(position)

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


def _visible_box(page) -> tuple[float, float, float, float, int]:
    """화면에 보이는 영역(CropBox 와 MediaBox 가 겹치는 곳)과 회전 각도."""
    media = page.mediabox
    crop = page.cropbox
    m_left, m_right = sorted((float(media.left), float(media.right)))
    m_bottom, m_top = sorted((float(media.bottom), float(media.top)))
    c_left, c_right = sorted((float(crop.left), float(crop.right)))
    c_bottom, c_top = sorted((float(crop.bottom), float(crop.top)))
    left, right = max(m_left, c_left), min(m_right, c_right)
    bottom, top = max(m_bottom, c_bottom), min(m_top, c_top)
    if right - left <= 1 or top - bottom <= 1:
        left, bottom, right, top = m_left, m_bottom, m_right, m_top
    try:
        rotation = int(page.rotation or 0) % 360
    except Exception:
        rotation = 0
    if rotation not in (0, 90, 180, 270):
        rotation = 0
    return left, bottom, right, top, rotation


def _visible_to_page(
    left: float, bottom: float, right: float, top: float, rotation: int
) -> Transformation:
    """보이는 화면 기준 좌표(왼쪽 아래가 0,0)를 페이지 좌표로 바꾸는 변환.

    /Rotate 는 페이지를 시계 방향으로 돌려 보여 주므로, 그 반대로 돌려 붙여야
    번호가 똑바로 서서 원하는 자리에 보인다.
    """
    if rotation == 90:
        matrix = (0, 1, -1, 0, right, bottom)
    elif rotation == 180:
        matrix = (-1, 0, 0, -1, right, top)
    elif rotation == 270:
        matrix = (0, -1, 1, 0, left, top)
    else:
        matrix = (1, 0, 0, 1, left, bottom)
    return Transformation(matrix)


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
            # 사용자가 화면에서 보는 모양(보이는 영역·회전)대로 번호 위치를 잡는다.
            left, bottom, right, top, rotation = _visible_box(page)
            if rotation in (90, 270):
                page_width, page_height = top - bottom, right - left
            else:
                page_width, page_height = right - left, top - bottom

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

            # 선택한 형식/위치 1회만 병합. 보이는 좌표를 페이지 좌표로 옮겨 붙인다.
            page.merge_transformed_page(
                overlay_page,
                _visible_to_page(left, bottom, right, top, rotation),
            )
            current_number += 1

        writer.add_page(page)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        writer.write(f)

    return output_path