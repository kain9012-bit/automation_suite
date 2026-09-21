"""엑셀 병합.

세 가지 방식
- files_to_sheets        : 파일(의 시트)마다 결과 파일의 시트 하나로 그대로 옮긴다. 서식·수식 유지.
- workbook_sheets_to_one : 넣은 모든 파일의 모든 시트를 한 시트로 이어 붙인다.
- same_sheets_together   : 여러 파일에서 이름이 같은 시트끼리 이어 붙인다.

이어 붙이는 두 방식은 실수가 나기 쉬운 곳을 막는다.
- 시트마다 헤더(제목) 행을 자동으로 찾되, 화면에서 확인하고 직접 고칠 수 있다(header_overrides).
- 파일마다 열 순서가 달라도 헤더 이름으로 맞춰 붙인다. 없는 열·새 열은 알려 준다.
- 숫자 서식(천 단위 쉼표, %, 날짜 등)을 원본 그대로 옮긴다.
- 저장한 뒤 결과 파일을 다시 열어 행 수가 맞는지 확인한다.
"""
from __future__ import annotations

import csv
import datetime as _dt
import re
from copy import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from openpyxl import Workbook, load_workbook
from openpyxl.cell.cell import MergedCell
from openpyxl.utils import get_column_letter, range_boundaries


MODE_WORKBOOK_SHEETS_TO_ONE = "workbook_sheets_to_one"
MODE_FILES_TO_SHEETS = "files_to_sheets"
MODE_SAME_SHEETS_TOGETHER = "same_sheets_together"

SUPPORTED_EXTENSIONS = {".xlsx", ".xlsm", ".csv"}

# 헤더를 찾을 때 위에서부터 볼 행 수.
HEADER_SCAN_ROWS = 50


@dataclass
class MergeOptions:
    mode: str
    source_paths: list[Path]
    output_path: Path
    add_source_file: bool = False
    add_source_sheet: bool = False
    include_hidden_sheets: bool = False
    # (파일 경로 문자열, 시트 이름) → 헤더 마지막 행 번호(1부터). 화면에서 직접 고친 값.
    header_overrides: dict = field(default_factory=dict)


@dataclass
class MergeResult:
    output_path: Path
    sheet_count: int = 0
    data_row_count: int = 0
    skipped_count: int = 0
    warnings: list[str] = field(default_factory=list)
    # 저장 후 결과 파일을 다시 열어 센 데이터 행 수. 기대값과 같으면 verified=True.
    verified: bool = False
    verify_message: str = ""


@dataclass
class SheetData:
    file_path: Path
    sheet_name: str
    rows: list[list]
    header_row: int
    formats: list[list] = field(default_factory=list)
    auto_header_row: int = 1
    hidden: bool = False
    # 수식은 있는데 저장된 결과값이 없어 빈 칸으로 읽힌 셀 수.
    missing_formula_values: int = 0

    @property
    def key(self) -> tuple[str, str]:
        return (str(self.file_path), self.sheet_name)


# ---------------------------------------------------------------- 기본 도우미

def is_supported_file(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def safe_file_name(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", str(name or ""))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"[\.\s]+$", "", cleaned)
    return cleaned or "result"


def safe_sheet_title(name: str) -> str:
    cleaned = re.sub(r"[\[\]\:\*\?\/\\]", "_", str(name or "Sheet1")).strip()
    return (cleaned or "Sheet1")[:31]


def unique_sheet_title(base: str, used: set[str]) -> str:
    safe = safe_sheet_title(base)
    candidate = safe
    index = 1
    while candidate.lower() in used:
        index += 1
        suffix = f"({index})"
        candidate = f"{safe[:31 - len(suffix)]}{suffix}"
    used.add(candidate.lower())
    return candidate


def normalize_value(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip()
    return value


def is_empty_row(row: list) -> bool:
    return all(normalize_value(value) == "" for value in row)


def trim_trailing_empty(row: list) -> list:
    values = list(row)
    while values and normalize_value(values[-1]) == "":
        values.pop()
    return values


def pad_row(row: list, width: int, fill="") -> list:
    values = list(row[:width])
    if len(values) < width:
        values.extend([fill] * (width - len(values)))
    return values


def _read_csv_rows(path: Path) -> list[list[str]]:
    encodings = ("utf-8-sig", "cp949", "euc-kr")
    last_error: Exception | None = None
    for encoding in encodings:
        try:
            with path.open("r", encoding=encoding, newline="") as fp:
                return [row for row in csv.reader(fp)]
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error:
        raise last_error
    return []


_CSV_NUMBER = re.compile(r"-?(0|[1-9]\d*)(\.\d+)?")


def _csv_value(value: str):
    """CSV 의 숫자 글자는 숫자로 바꾼다. 0 으로 시작하는 코드(0012 등)는 글자 그대로 둔다."""
    text = value.strip()
    if _CSV_NUMBER.fullmatch(text):
        return float(text) if "." in text else int(text)
    return value


def load_source_workbook(path: Path, data_only: bool = False):
    ext = path.suffix.lower()
    if ext == ".xls":
        raise ValueError(".xls 파일은 직접 지원하지 않습니다. 엑셀에서 .xlsx로 저장한 뒤 사용해 주세요.")
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError("지원하는 파일 형식은 .xlsx, .xlsm, .csv 입니다.")

    if ext == ".csv":
        wb = Workbook()
        ws = wb.active
        ws.title = safe_sheet_title(path.stem)
        for row in _read_csv_rows(path):
            ws.append([_csv_value(value) for value in row])
        return wb, True

    return load_workbook(path, data_only=data_only), False


# ---------------------------------------------------------------- 시트 읽기

def worksheet_rows_and_formats(ws) -> tuple[list[list], list[list]]:
    """셀 값과 숫자 서식을 함께 읽는다. 서식은 결과 파일에 그대로 옮긴다."""
    rows: list[list] = []
    formats: list[list] = []
    max_col = ws.max_column or 1
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row or 1, min_col=1, max_col=max_col):
        rows.append([normalize_value(cell.value) for cell in row])
        formats.append([cell.number_format or "General" for cell in row])
    # 끝쪽 빈 행은 버린다(서식만 남은 행 등).
    while rows and is_empty_row(rows[-1]):
        rows.pop()
        formats.pop()
    return rows, formats


def worksheet_to_rows(ws) -> list[list]:
    return worksheet_rows_and_formats(ws)[0]


def detect_header_row_from_rows(rows: list[list], max_scan_rows: int = HEADER_SCAN_ROWS) -> int:
    """칸이 가장 많이 채워지고 글자가 많은 행을 헤더로 본다.

    같은 점수면 위쪽 행을 고른다. 헤더 바로 아래 데이터 행이 칸을 더 채워도
    헤더가 뽑히도록 숫자 칸은 점수를 낮게 준다.
    """
    best_index = 1
    best_score = -1
    for idx, row in enumerate(rows[:max_scan_rows], start=1):
        values = [normalize_value(value) for value in row]
        nonempty = [value for value in values if value != ""]
        if not nonempty:
            continue
        text_count = sum(
            1
            for value in nonempty
            if isinstance(value, str) and not re.fullmatch(r"[\d,.%\-\s]+", value)
        )
        number_count = len(nonempty) - text_count
        score = text_count * 4 + number_count
        if score > best_score:
            best_score = score
            best_index = idx
    return best_index


def _count_missing_formula_values(path: Path, sheet_name: str, rows: list[list]) -> int:
    """수식은 있는데 저장된 결과값이 없는 셀 수. (엑셀이 아닌 프로그램이 저장한 파일 등)
    이런 셀은 병합 결과에서 빈 칸이 되므로 미리 알려 준다."""
    if path.suffix.lower() == ".csv":
        return 0
    try:
        wb = load_workbook(path, data_only=False, read_only=True)
        ws = wb[sheet_name]
        count = 0
        for r_idx, row in enumerate(ws.iter_rows(values_only=True)):
            if r_idx >= len(rows):
                break
            for c_idx, value in enumerate(row):
                if isinstance(value, str) and value.startswith("="):
                    cached = rows[r_idx][c_idx] if c_idx < len(rows[r_idx]) else ""
                    if cached == "":
                        count += 1
        wb.close()
        return count
    except Exception:
        return 0


def collect_sheet_data(
    path: Path,
    include_hidden_sheets: bool = False,
    header_overrides: dict | None = None,
    check_formulas: bool = True,
) -> list[SheetData]:
    wb_values, _ = load_source_workbook(path, data_only=True)
    collected: list[SheetData] = []
    for ws in wb_values.worksheets:
        hidden = ws.sheet_state != "visible"
        if not include_hidden_sheets and hidden:
            continue
        rows, formats = worksheet_rows_and_formats(ws)
        if not rows:
            continue
        auto = detect_header_row_from_rows(rows)
        header = auto
        if header_overrides:
            manual = header_overrides.get((str(path), ws.title))
            if manual:
                header = max(0, min(int(manual), len(rows)))
        sheet = SheetData(path, ws.title, rows, header, formats, auto, hidden)
        if check_formulas:
            sheet.missing_formula_values = _count_missing_formula_values(path, ws.title, rows)
        collected.append(sheet)
    return collected


# ---------------------------------------------------------------- 열 맞추기

def _norm_name(value) -> str:
    return re.sub(r"\s+", "", str(normalize_value(value))).lower()


def header_names(sheet: SheetData, width: int) -> list[str]:
    """열마다 헤더 이름. 기본은 헤더 마지막 줄의 글자.

    마지막 줄이 비어 있으면(위 칸과 병합된 2단 헤더) 바로 위 줄들에서 찾는다.
    칸 하나만 채워진 줄(표 제목 '2026년 3월 현황' 같은 줄)은 열 이름으로 쓰지 않는다.
    """
    header_rows = sheet.rows[: sheet.header_row]
    usable = [
        row for row in header_rows
        if sum(1 for value in row if normalize_value(value) != "") > 1
    ] or header_rows[-1:]
    names = []
    for col in range(width):
        name = ""
        for row in reversed(usable[-3:]):
            value = normalize_value(row[col]) if col < len(row) else ""
            if value != "":
                name = str(value)
                break
        names.append(name)
    return names


def column_keys(names: list[str]) -> list[tuple[str, int]]:
    """(이름, 같은 이름 중 몇 번째) 로 열을 구분한다. '비고'가 두 번 나와도 섞이지 않게."""
    seen: dict[str, int] = {}
    keys = []
    for col, name in enumerate(names):
        norm = _norm_name(name)
        if norm == "":
            norm = f"#빈헤더{col}"  # 이름 없는 열은 위치로 맞춘다
        seen[norm] = seen.get(norm, 0) + 1
        keys.append((norm, seen[norm]))
    return keys


def sheet_width(sheet: SheetData) -> int:
    width = 0
    for row in sheet.rows:
        width = max(width, len(trim_trailing_empty(row)))
    return max(width, 1)


def _label(sheet: SheetData, multi_file: bool) -> str:
    return f"{sheet.file_path.name} › {sheet.sheet_name}" if multi_file else sheet.sheet_name


def build_merged(
    sheets: list[SheetData],
    add_source_file: bool,
    add_source_sheet: bool,
) -> dict:
    """여러 시트를 한 표로 이어 붙인다. 열은 헤더 이름으로 맞춘다.

    돌려주는 값: rows, formats, header_rows(결과의 헤더 줄 수), data_count, notes(알림)
    """
    if not sheets:
        return {"rows": [], "formats": [], "header_rows": 0, "data_count": 0, "notes": []}

    multi_file = len({str(sheet.file_path) for sheet in sheets}) > 1
    base = sheets[0]
    base_width = sheet_width(base)
    base_names = header_names(base, base_width)
    base_keys = column_keys(base_names)
    columns = list(base_keys)
    column_names = list(base_names)
    notes: list[str] = []

    # 시트마다 '원본 열 → 결과 열' 대응표를 만든다.
    mappings: list[list[int]] = []
    for sheet in sheets:
        width = sheet_width(sheet)
        names = header_names(sheet, width)
        keys = column_keys(names)
        if sheet is base:
            mappings.append(list(range(width)))
            continue
        if keys[: len(base_keys)] == base_keys and len(keys) <= len(columns):
            mappings.append(list(range(width)))
            continue
        mapping = []
        added = []
        index_of = {key: idx for idx, key in enumerate(columns)}
        for col, key in enumerate(keys):
            if key in index_of:
                mapping.append(index_of[key])
            else:
                columns.append(key)
                column_names.append(names[col])
                index_of[key] = len(columns) - 1
                mapping.append(len(columns) - 1)
                if names[col]:
                    added.append(names[col])
        mappings.append(mapping)
        label = _label(sheet, multi_file)
        present = set(keys)
        missing = [base_names[i] for i, key in enumerate(base_keys) if key not in present and base_names[i]]
        reordered = [m for m in mapping if m < len(base_keys)] != sorted(m for m in mapping if m < len(base_keys))
        if added:
            notes.append(f"{label}: 첫 시트에 없는 열 {len(added)}개를 오른쪽에 붙였습니다 ({', '.join(added[:5])}{' 외' if len(added) > 5 else ''})")
        if missing:
            notes.append(f"{label}: 없는 열 {len(missing)}개는 빈 칸으로 둡니다 ({', '.join(missing[:5])}{' 외' if len(missing) > 5 else ''})")
        if reordered and not added and not missing:
            notes.append(f"{label}: 열 순서가 달라 항목명으로 맞췄습니다")

    width = len(columns)
    extra_headers: list[str] = []
    if add_source_file:
        extra_headers.append("원본파일")
    if add_source_sheet:
        extra_headers.append("원본시트")

    header_count = base.header_row
    out_rows: list[list] = []
    out_formats: list[list] = []
    base_header_rows = base.rows[:header_count]
    for idx in range(header_count):
        row = pad_row(base_header_rows[idx], width)
        fmt = pad_row(base.formats[idx] if idx < len(base.formats) else [], width, "General")
        # 다른 시트에서 새로 붙은 열은 마지막 헤더 줄에 이름을 적는다.
        if idx == header_count - 1:
            for col in range(base_width, width):
                row[col] = column_names[col]
        if extra_headers:
            row.extend(extra_headers if idx == header_count - 1 else [""] * len(extra_headers))
            fmt.extend(["General"] * len(extra_headers))
        out_rows.append(row)
        out_formats.append(fmt)

    data_count = 0
    for sheet, mapping in zip(sheets, mappings):
        for r_idx in range(sheet.header_row, len(sheet.rows)):
            src = sheet.rows[r_idx]
            if is_empty_row(src):
                continue
            src_fmt = sheet.formats[r_idx] if r_idx < len(sheet.formats) else []
            line = [""] * width
            fmt = ["General"] * width
            for col, value in enumerate(src):
                if col >= len(mapping):
                    # 헤더보다 오른쪽에 값이 있는 드문 경우: 새 열로 붙인다.
                    columns.append(("#추가", col))
                    column_names.append("")
                    mapping.append(len(columns) - 1)
                    line.append("")
                    fmt.append("General")
                    width = len(columns)
                target = mapping[col]
                if target >= len(line):
                    line.extend([""] * (target + 1 - len(line)))
                    fmt.extend(["General"] * (target + 1 - len(fmt)))
                line[target] = value
                if col < len(src_fmt):
                    fmt[target] = src_fmt[col]
            if add_source_file:
                line.append(sheet.file_path.name)
                fmt.append("General")
            if add_source_sheet:
                line.append(sheet.sheet_name)
                fmt.append("General")
            out_rows.append(line)
            out_formats.append(fmt)
            data_count += 1

    return {
        "rows": out_rows,
        "formats": out_formats,
        "header_rows": header_count,
        "data_count": data_count,
        "notes": notes,
        "columns": width + len(extra_headers),
    }


# ---------------------------------------------------------------- 쓰기

def _copy_cell(src, dst) -> None:
    dst.value = src.value
    if src.has_style:
        dst.font = copy(src.font)
        dst.fill = copy(src.fill)
        dst.border = copy(src.border)
        dst.alignment = copy(src.alignment)
        dst.protection = copy(src.protection)
    dst.number_format = src.number_format
    if src.hyperlink:
        dst._hyperlink = copy(src.hyperlink)
    if src.comment:
        dst.comment = copy(src.comment)


def copy_worksheet_full(ws_in, wb_out: Workbook, title: str):
    ws_out = wb_out.create_sheet(title)
    for col_idx in range(1, (ws_in.max_column or 1) + 1):
        letter = get_column_letter(col_idx)
        src_dim = ws_in.column_dimensions.get(letter)
        if src_dim is not None:
            dst_dim = ws_out.column_dimensions[letter]
            dst_dim.width = src_dim.width
            dst_dim.hidden = src_dim.hidden
            dst_dim.outlineLevel = src_dim.outlineLevel

    for row_idx in range(1, (ws_in.max_row or 0) + 1):
        src_dim = ws_in.row_dimensions.get(row_idx)
        if src_dim is not None:
            dst_dim = ws_out.row_dimensions[row_idx]
            dst_dim.height = src_dim.height
            dst_dim.hidden = src_dim.hidden
            dst_dim.outlineLevel = src_dim.outlineLevel
        for col_idx in range(1, (ws_in.max_column or 1) + 1):
            _copy_cell(ws_in.cell(row=row_idx, column=col_idx), ws_out.cell(row=row_idx, column=col_idx))

    for merged in list(ws_in.merged_cells.ranges):
        try:
            ws_out.merge_cells(str(merged))
        except Exception:
            pass
    if ws_in.freeze_panes:
        ws_out.freeze_panes = ws_in.freeze_panes
    return ws_out


def apply_header_style(sample_path: Path, sample_sheet_name: str, ws_out, header_row: int, width: int) -> None:
    """첫 시트의 헤더 모양(글꼴·색·테두리·열 너비·병합)을 결과에 옮긴다. 값은 나중에 다시 쓴다."""
    try:
        wb_style, _ = load_source_workbook(sample_path, data_only=False)
        ws_style = wb_style[sample_sheet_name] if sample_sheet_name in wb_style.sheetnames else wb_style.worksheets[0]
        for col_idx in range(1, min(width, ws_style.max_column or width) + 1):
            letter = get_column_letter(col_idx)
            src_dim = ws_style.column_dimensions.get(letter)
            if src_dim is not None:
                ws_out.column_dimensions[letter].width = src_dim.width

        for row_idx in range(1, min(header_row, ws_style.max_row or header_row) + 1):
            src_dim = ws_style.row_dimensions.get(row_idx)
            if src_dim is not None:
                ws_out.row_dimensions[row_idx].height = src_dim.height
            for col_idx in range(1, min(width, ws_style.max_column or width) + 1):
                _copy_cell(ws_style.cell(row=row_idx, column=col_idx), ws_out.cell(row=row_idx, column=col_idx))

        for merged in list(ws_style.merged_cells.ranges):
            min_col, min_row, max_col, max_row = range_boundaries(str(merged))
            if min_row <= header_row and max_row <= header_row and max_col <= width:
                try:
                    ws_out.merge_cells(str(merged))
                except Exception:
                    pass
    except Exception:
        return


def write_merged_sheet(wb_out: Workbook, title: str, merged: dict, sample: SheetData) -> None:
    ws_out = wb_out.create_sheet(title)
    rows = merged["rows"]
    formats = merged["formats"]
    width = max((len(row) for row in rows), default=1)
    header_rows = merged["header_rows"]
    if header_rows:
        apply_header_style(sample.file_path, sample.sheet_name, ws_out, header_rows, width)
    for r_idx, row in enumerate(rows, start=1):
        fmt_row = formats[r_idx - 1] if r_idx - 1 < len(formats) else []
        for c_idx in range(1, width + 1):
            cell = ws_out.cell(row=r_idx, column=c_idx)
            if isinstance(cell, MergedCell):
                continue
            value = row[c_idx - 1] if c_idx <= len(row) else None
            cell.value = None if value == "" else value
            if r_idx > header_rows and c_idx <= len(fmt_row):
                number_format = fmt_row[c_idx - 1]
                if number_format and number_format != "General":
                    cell.number_format = number_format
    if header_rows:
        ws_out.freeze_panes = ws_out.cell(row=header_rows + 1, column=1)


def _verify_output(path: Path, expected: dict[str, tuple[int, int]]) -> tuple[bool, str]:
    """저장한 결과 파일을 다시 열어 시트별 데이터 행 수가 기대값과 같은지 센다.
    expected: 시트 이름 → (헤더 줄 수, 데이터 행 수)"""
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
        problems = []
        for title, (header_rows, want) in expected.items():
            if title not in wb.sheetnames:
                problems.append(f"'{title}' 시트가 없습니다")
                continue
            got = 0
            for idx, row in enumerate(wb[title].iter_rows(values_only=True), start=1):
                if idx <= header_rows:
                    continue
                if any(value not in (None, "") for value in row):
                    got += 1
            if got != want:
                problems.append(f"'{title}' 시트 데이터 {want}행 중 {got}행만 확인됨")
        wb.close()
        if problems:
            return False, "; ".join(problems)
        return True, "결과 파일을 다시 열어 행 수를 확인했습니다."
    except Exception as exc:
        return False, f"결과 파일 확인 실패: {exc}"


# ---------------------------------------------------------------- 병합 실행

def _collect_all(options: MergeOptions, result: MergeResult, log) -> list[SheetData]:
    sheets: list[SheetData] = []
    for path in options.source_paths:
        try:
            found = collect_sheet_data(path, options.include_hidden_sheets, options.header_overrides)
            if not found:
                result.warnings.append(f"{path.name}: 내용이 있는 시트가 없습니다.")
                result.skipped_count += 1
            sheets.extend(found)
        except Exception as exc:
            result.skipped_count += 1
            result.warnings.append(f"{path.name}: {exc}")
    for sheet in sheets:
        if sheet.missing_formula_values:
            result.warnings.append(
                f"{sheet.file_path.name} › {sheet.sheet_name}: 수식 결과가 저장돼 있지 않은 셀 "
                f"{sheet.missing_formula_values}개가 빈 칸이 됩니다. 원본을 엑셀에서 열어 저장한 뒤 다시 병합하세요."
            )
    return sheets


def merge_workbook_sheets_to_one(options: MergeOptions, log: Callable[[str], None] | None = None) -> MergeResult:
    result = MergeResult(options.output_path)
    sheets = _collect_all(options, result, log)
    if not sheets:
        raise ValueError("병합할 시트를 찾지 못했습니다.")
    merged = build_merged(sheets, options.add_source_file, options.add_source_sheet)
    result.warnings.extend(merged["notes"])
    wb_out = Workbook()
    wb_out.remove(wb_out.active)
    write_merged_sheet(wb_out, "병합", merged, sheets[0])
    wb_out.save(options.output_path)
    result.sheet_count = 1
    result.data_row_count = merged["data_count"]
    result.verified, result.verify_message = _verify_output(
        options.output_path, {"병합": (merged["header_rows"], merged["data_count"])}
    )
    if log:
        log(f"시트 {len(sheets)}개를 한 시트로 병합했습니다. 데이터 {merged['data_count']}행")
    return result


def merge_same_sheets_together(options: MergeOptions, log: Callable[[str], None] | None = None) -> MergeResult:
    result = MergeResult(options.output_path)
    sheets = _collect_all(options, result, log)
    groups: dict[str, list[SheetData]] = {}
    for sheet in sheets:
        groups.setdefault(sheet.sheet_name, []).append(sheet)
    if not groups:
        raise ValueError("병합할 시트를 찾지 못했습니다.")

    wb_out = Workbook()
    wb_out.remove(wb_out.active)
    used: set[str] = set()
    expected: dict[str, tuple[int, int]] = {}
    for sheet_name, group in groups.items():
        merged = build_merged(group, options.add_source_file, options.add_source_sheet)
        result.warnings.extend(merged["notes"])
        title = unique_sheet_title(sheet_name, used)
        write_merged_sheet(wb_out, title, merged, group[0])
        expected[title] = (merged["header_rows"], merged["data_count"])
        result.sheet_count += 1
        result.data_row_count += merged["data_count"]
        if log:
            log(f"같은 시트명 병합: {sheet_name} ({len(group)}개 파일) → 데이터 {merged['data_count']}행")

    wb_out.save(options.output_path)
    result.verified, result.verify_message = _verify_output(options.output_path, expected)
    return result


def _files_to_sheets_plan(options: MergeOptions) -> tuple[list[tuple[Path, str, str]], list[str]]:
    """(파일, 시트, 결과 시트 이름) 목록. 파일에 시트가 하나면 파일 이름, 여럿이면 '파일_시트'."""
    plan = []
    warnings = []
    used: set[str] = set()
    for path in options.source_paths:
        try:
            if path.suffix.lower() == ".csv":
                names = [path.stem]
            else:
                wb = load_workbook(path, read_only=True)
                names = [
                    ws.title for ws in wb.worksheets
                    if options.include_hidden_sheets or ws.sheet_state == "visible"
                ]
                wb.close()
            if not names:
                warnings.append(f"{path.name}: 보이는 시트가 없습니다.")
                continue
            for name in names:
                base = path.stem if len(names) == 1 else f"{path.stem}_{name}"
                plan.append((path, name, unique_sheet_title(base, used)))
        except Exception as exc:
            warnings.append(f"{path.name}: {exc}")
    return plan, warnings


def merge_files_to_sheets(options: MergeOptions, log: Callable[[str], None] | None = None) -> MergeResult:
    """파일의 모든 보이는 시트를 서식·수식 그대로 결과 파일의 시트로 옮긴다."""
    result = MergeResult(options.output_path)
    plan, warnings = _files_to_sheets_plan(options)
    result.warnings.extend(warnings)
    result.skipped_count += len(warnings)
    wb_out = Workbook()
    wb_out.remove(wb_out.active)
    opened: dict[str, object] = {}
    for path, sheet_name, title in plan:
        try:
            key = str(path)
            if key not in opened:
                opened[key] = load_source_workbook(path, data_only=False)[0]
            wb_in = opened[key]
            ws_in = wb_in[sheet_name] if sheet_name in wb_in.sheetnames else wb_in.worksheets[0]
            copy_worksheet_full(ws_in, wb_out, title)
            result.sheet_count += 1
            if log:
                log(f"시트 추가: {path.name} › {sheet_name} → {title}")
        except Exception as exc:
            result.skipped_count += 1
            result.warnings.append(f"{path.name} › {sheet_name}: {exc}")

    if result.sheet_count == 0:
        raise ValueError("결과 파일에 추가할 시트가 없습니다.")
    wb_out.save(options.output_path)
    try:
        wb = load_workbook(options.output_path, read_only=True)
        got = len(wb.sheetnames)
        wb.close()
        result.verified = got == result.sheet_count
        result.verify_message = (
            "결과 파일을 다시 열어 시트 수를 확인했습니다."
            if result.verified
            else f"시트 {result.sheet_count}개 중 {got}개만 확인됨"
        )
    except Exception as exc:
        result.verify_message = f"결과 파일 확인 실패: {exc}"
    return result


def merge_excel(options: MergeOptions, log: Callable[[str], None] | None = None) -> MergeResult:
    if not options.source_paths:
        raise ValueError("병합할 파일이 없습니다.")
    for path in options.source_paths:
        if not path.exists():
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {path}")
        if not is_supported_file(path):
            raise ValueError(f"지원하지 않는 파일 형식입니다: {path.name}")
        if path.resolve() == options.output_path.resolve():
            raise ValueError(f"결과 파일이 원본과 같습니다: {path.name}")

    options.output_path.parent.mkdir(parents=True, exist_ok=True)

    if log:
        log(f"저장 파일: {options.output_path}")
        log(f"대상 파일: {len(options.source_paths)}개")

    if options.mode == MODE_FILES_TO_SHEETS:
        return merge_files_to_sheets(options, log)
    if options.mode == MODE_SAME_SHEETS_TOGETHER:
        return merge_same_sheets_together(options, log)
    return merge_workbook_sheets_to_one(options, log)


# ---------------------------------------------------------------- 미리보기(화면용)

def _cell_text(value, limit: int = 40, number_format: str = ""):
    if value in ("", None):
        return ""
    # 화면 미리보기에서도 엑셀에서 보이는 모양(%, 쉼표)에 가깝게 보여 준다.
    if isinstance(value, (int, float)) and not isinstance(value, bool) and number_format:
        if "%" in number_format:
            return f"{value * 100:,.10g}%"
    if isinstance(value, _dt.datetime):
        return value.strftime("%Y-%m-%d") if value.time() == _dt.time() else value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, _dt.date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return value
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _preview_table(rows: list[list], count: int, max_cols: int = 30, formats: list[list] | None = None) -> list[list]:
    table = []
    for r_idx, row in enumerate(rows[:count]):
        fmt_row = formats[r_idx] if formats and r_idx < len(formats) else []
        table.append([
            _cell_text(v, number_format=fmt_row[c] if c < len(fmt_row) else "")
            for c, v in enumerate(row[:max_cols])
        ])
    return table


def analyze_merge(
    paths: list[Path],
    mode: str,
    include_hidden_sheets: bool = False,
    header_overrides: dict | None = None,
    add_source_file: bool = False,
    add_source_sheet: bool = False,
    preview_rows: int = 15,
) -> dict:
    """병합 전에 화면에 보여 줄 정보: 시트별 자동 헤더와 위쪽 행, 결과 미리보기."""
    errors = []
    if mode == MODE_FILES_TO_SHEETS:
        options = MergeOptions(mode, paths, Path("."), include_hidden_sheets=include_hidden_sheets)
        plan, warnings = _files_to_sheets_plan(options)
        return {
            "mode": mode,
            "sheets": [
                {"file": str(p), "file_name": p.name, "sheet": s, "result_title": t}
                for p, s, t in plan
            ],
            "results": [],
            "errors": warnings,
        }

    sheets: list[SheetData] = []
    for path in paths:
        try:
            found = collect_sheet_data(path, include_hidden_sheets, header_overrides)
            if not found:
                errors.append(f"{path.name}: 내용이 있는 시트가 없습니다.")
            sheets.extend(found)
        except Exception as exc:
            errors.append(f"{path.name}: {exc}")

    sheet_infos = []
    for sheet in sheets:
        show = min(len(sheet.rows), max(10, sheet.header_row + 6))
        sheet_infos.append({
            "file": str(sheet.file_path),
            "file_name": sheet.file_path.name,
            "sheet": sheet.sheet_name,
            "hidden": sheet.hidden,
            "row_count": len(sheet.rows),
            "data_rows": sum(1 for row in sheet.rows[sheet.header_row:] if not is_empty_row(row)),
            "header_row": sheet.header_row,
            "auto_header_row": sheet.auto_header_row,
            "missing_formula_values": sheet.missing_formula_values,
            "preview": _preview_table(sheet.rows, show, formats=sheet.formats),
        })

    groups: list[tuple[str, list[SheetData]]] = []
    if mode == MODE_SAME_SHEETS_TOGETHER:
        by_name: dict[str, list[SheetData]] = {}
        for sheet in sheets:
            by_name.setdefault(sheet.sheet_name, []).append(sheet)
        groups = list(by_name.items())
    elif sheets:
        groups = [("병합", sheets)]

    results = []
    for title, group in groups:
        merged = build_merged(group, add_source_file, add_source_sheet)
        header_rows = merged["header_rows"]
        results.append({
            "title": title,
            "sheet_count": len(group),
            "data_rows": merged["data_count"],
            "columns": merged["columns"],
            "header_rows": header_rows,
            "header": _preview_table(merged["rows"][:header_rows], header_rows),
            "rows": _preview_table(
                merged["rows"][header_rows:], preview_rows, formats=merged["formats"][header_rows:]
            ),
            "notes": merged["notes"],
        })

    return {"mode": mode, "sheets": sheet_infos, "results": results, "errors": errors}
