
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from pypdf import PdfReader, PdfWriter


@dataclass
class PreviewSummary:
    action_text: str
    detail_text: str
    page_count: int


def parse_page_spec(spec: str, total_pages: int) -> list[int]:
    spec = (spec or "").strip()
    if not spec:
        raise ValueError("페이지 번호를 입력해 주세요.")
    pages: set[int] = set()
    tokens = [t.strip() for t in spec.split(",") if t.strip()]
    if not tokens:
        raise ValueError("페이지 번호를 올바르게 입력해 주세요.")
    for token in tokens:
        if "-" in token:
            m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", token)
            if not m:
                raise ValueError(f"잘못된 범위 형식입니다: {token}")
            start = int(m.group(1)); end = int(m.group(2))
            if start > end:
                raise ValueError(f"범위 시작값이 끝값보다 큽니다: {token}")
            for p in range(start, end + 1):
                if p < 1 or p > total_pages:
                    raise ValueError(f"존재하지 않는 페이지 번호가 포함되어 있습니다: {p}")
                pages.add(p)
        else:
            if not token.isdigit():
                raise ValueError(f"잘못된 페이지 번호 형식입니다: {token}")
            p = int(token)
            if p < 1 or p > total_pages:
                raise ValueError(f"존재하지 않는 페이지 번호가 포함되어 있습니다: {p}")
            pages.add(p)
    return sorted(pages)


def parse_page_order_spec(spec: str, total_pages: int) -> list[int]:
    spec = (spec or "").strip()
    if not spec:
        raise ValueError("새 페이지 순서를 입력해 주세요.")

    pages: list[int] = []
    tokens = [t.strip() for t in spec.split(",") if t.strip()]
    if not tokens:
        raise ValueError("새 페이지 순서를 올바르게 입력해 주세요.")

    for token in tokens:
        if "-" in token:
            m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", token)
            if not m:
                raise ValueError(f"잘못된 범위 형식입니다: {token}")
            start = int(m.group(1))
            end = int(m.group(2))
            step = 1 if start <= end else -1
            for page_no in range(start, end + step, step):
                _validate_page_no(page_no, total_pages)
                pages.append(page_no)
        else:
            if not token.isdigit():
                raise ValueError(f"잘못된 페이지 번호 형식입니다: {token}")
            page_no = int(token)
            _validate_page_no(page_no, total_pages)
            pages.append(page_no)

    expected = set(range(1, total_pages + 1))
    actual = set(pages)
    duplicates = sorted({page_no for page_no in pages if pages.count(page_no) > 1})
    missing = sorted(expected - actual)

    if duplicates:
        raise ValueError(f"중복된 페이지 번호가 있습니다: {', '.join(map(str, duplicates))}")
    if missing:
        raise ValueError(f"빠진 페이지 번호가 있습니다: {', '.join(map(str, missing[:20]))}")
    if len(pages) != total_pages:
        raise ValueError("새 페이지 순서는 전체 페이지를 한 번씩 모두 포함해야 합니다.")

    return pages


def _validate_page_no(page_no: int, total_pages: int) -> None:
    if page_no < 1 or page_no > total_pages:
        raise ValueError(f"존재하지 않는 페이지 번호입니다: {page_no}")


def build_move_order(total_pages: int, source_page: int, target_position: int) -> list[int]:
    _validate_page_no(source_page, total_pages)
    _validate_page_no(target_position, total_pages)

    pages = list(range(1, total_pages + 1))
    pages.remove(source_page)
    pages.insert(target_position - 1, source_page)
    return pages


def build_swap_order(total_pages: int, first_page: int, second_page: int) -> list[int]:
    _validate_page_no(first_page, total_pages)
    _validate_page_no(second_page, total_pages)
    if first_page == second_page:
        raise ValueError("서로 다른 두 페이지를 선택해 주세요.")

    pages = list(range(1, total_pages + 1))
    first_index = pages.index(first_page)
    second_index = pages.index(second_page)
    pages[first_index], pages[second_index] = pages[second_index], pages[first_index]
    return pages


def _format_pages(pages: list[int], limit: int = 20) -> str:
    shown = ", ".join(map(str, pages[:limit]))
    if len(pages) > limit:
        shown += ", ..."
    return shown


def get_total_pages(pdf_path: Path) -> int:
    reader = PdfReader(str(pdf_path))
    if getattr(reader, "is_encrypted", False):
        try:
            if reader.decrypt("") == 0:
                raise RuntimeError("암호가 설정된 PDF입니다.")
        except Exception:
            raise RuntimeError("암호가 설정된 PDF입니다.")
    return len(reader.pages)


def _load_reader(pdf_path: Path) -> PdfReader:
    reader = PdfReader(str(pdf_path))
    if getattr(reader, "is_encrypted", False):
        try:
            if reader.decrypt("") == 0:
                raise RuntimeError("암호가 설정된 PDF입니다.")
        except Exception:
            raise RuntimeError("암호가 설정된 PDF입니다.")
    return reader


def _safe_stem(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", name).strip() or "output"


def build_unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    idx = 1
    while True:
        candidate = path.with_name(f"{stem}({idx}){suffix}")
        if not candidate.exists():
            return candidate
        idx += 1


def write_pages_to_pdf(reader: PdfReader, page_numbers_1based: Iterable[int], output_path: Path) -> Path:
    writer = PdfWriter()
    for page_no in page_numbers_1based:
        writer.add_page(reader.pages[page_no - 1])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path = build_unique_path(output_path)
    with open(output_path, "wb") as f:
        writer.write(f)
    return output_path


def preview_extract(pdf_path: Path, mode: str, spec: str = "") -> PreviewSummary:
    total = get_total_pages(pdf_path)
    if mode == "pages":
        pages = parse_page_spec(spec, total)
        return PreviewSummary(f"총 {total}페이지 중 {', '.join(map(str, pages))}페이지 추출 예정", f"추출 페이지 수: {len(pages)}개", total)
    if mode == "odd":
        pages = list(range(1, total + 1, 2))
        return PreviewSummary(f"총 {total}페이지 중 홀수 페이지 추출 예정", f"추출 페이지 수: {len(pages)}개", total)
    if mode == "even":
        pages = list(range(2, total + 1, 2))
        return PreviewSummary(f"총 {total}페이지 중 짝수 페이지 추출 예정", f"추출 페이지 수: {len(pages)}개", total)
    raise ValueError("지원하지 않는 추출 모드입니다.")


def run_extract(pdf_path: Path, output_dir: Path, mode: str, spec: str = "") -> Path:
    total = get_total_pages(pdf_path)
    reader = _load_reader(pdf_path)
    if mode == "pages":
        pages = parse_page_spec(spec, total)
        suffix = "_추출_" + "_".join(map(str, pages[:20]))
        if len(pages) > 20:
            suffix += "_etc"
    elif mode == "odd":
        pages = list(range(1, total + 1, 2))
        suffix = "_추출_홀수"
    elif mode == "even":
        pages = list(range(2, total + 1, 2))
        suffix = "_추출_짝수"
    else:
        raise ValueError("지원하지 않는 추출 모드입니다.")
    out_name = f"{_safe_stem(pdf_path.stem)}{suffix}.pdf"
    return write_pages_to_pdf(reader, pages, output_dir / out_name)


def preview_delete(pdf_path: Path, mode: str, spec: str = "") -> PreviewSummary:
    total = get_total_pages(pdf_path)
    if mode == "pages":
        delete_pages = parse_page_spec(spec, total)
        kept = [p for p in range(1, total + 1) if p not in set(delete_pages)]
        return PreviewSummary(f"총 {total}페이지 중 {', '.join(map(str, delete_pages))}페이지 삭제 예정", f"삭제 후 남는 페이지 수: {len(kept)}개", total)
    mapping = {
        "first": [1] if total >= 1 else [],
        "last": [total] if total >= 1 else [],
        "odd": list(range(1, total + 1, 2)),
        "even": list(range(2, total + 1, 2)),
    }
    if mode not in mapping:
        raise ValueError("지원하지 않는 삭제 모드입니다.")
    delete_pages = mapping[mode]
    kept = [p for p in range(1, total + 1) if p not in set(delete_pages)]
    mode_name = {"first":"첫 페이지","last":"마지막 페이지","odd":"홀수 페이지","even":"짝수 페이지"}[mode]
    return PreviewSummary(f"총 {total}페이지 중 {mode_name} 삭제 예정", f"삭제 후 남는 페이지 수: {len(kept)}개", total)


def run_delete(pdf_path: Path, output_dir: Path, mode: str, spec: str = "") -> Path:
    total = get_total_pages(pdf_path)
    reader = _load_reader(pdf_path)
    if mode == "pages":
        delete_pages = set(parse_page_spec(spec, total))
    elif mode == "first":
        delete_pages = {1} if total >= 1 else set()
    elif mode == "last":
        delete_pages = {total} if total >= 1 else set()
    elif mode == "odd":
        delete_pages = set(range(1, total + 1, 2))
    elif mode == "even":
        delete_pages = set(range(2, total + 1, 2))
    else:
        raise ValueError("지원하지 않는 삭제 모드입니다.")
    keep_pages = [p for p in range(1, total + 1) if p not in delete_pages]
    if not keep_pages:
        raise ValueError("삭제 후 남는 페이지가 없습니다.")
    out_name = f"{_safe_stem(pdf_path.stem)}_삭제후.pdf"
    return write_pages_to_pdf(reader, keep_pages, output_dir / out_name)


def preview_reorder(
    pdf_path: Path,
    mode: str,
    spec: str = "",
    source_page: int = 1,
    target_page: int = 1,
) -> PreviewSummary:
    total = get_total_pages(pdf_path)
    if mode == "sequence":
        pages = parse_page_order_spec(spec, total)
        return PreviewSummary(
            f"총 {total}페이지를 입력한 순서대로 재배열할 예정",
            f"새 순서: {_format_pages(pages)}",
            total,
        )
    if mode == "move":
        pages = build_move_order(total, source_page, target_page)
        return PreviewSummary(
            f"{source_page}페이지를 {target_page}번째 위치로 이동할 예정",
            f"새 순서: {_format_pages(pages)}",
            total,
        )
    if mode == "swap":
        pages = build_swap_order(total, source_page, target_page)
        return PreviewSummary(
            f"{source_page}페이지와 {target_page}페이지의 위치를 맞바꿀 예정",
            f"새 순서: {_format_pages(pages)}",
            total,
        )
    raise ValueError("지원하지 않는 재배열 모드입니다.")


def run_reorder(
    pdf_path: Path,
    output_dir: Path,
    mode: str,
    spec: str = "",
    source_page: int = 1,
    target_page: int = 1,
) -> Path:
    total = get_total_pages(pdf_path)
    reader = _load_reader(pdf_path)
    if mode == "sequence":
        pages = parse_page_order_spec(spec, total)
    elif mode == "move":
        pages = build_move_order(total, source_page, target_page)
    elif mode == "swap":
        pages = build_swap_order(total, source_page, target_page)
    else:
        raise ValueError("지원하지 않는 재배열 모드입니다.")

    out_name = f"{_safe_stem(pdf_path.stem)}_재배열.pdf"
    return write_pages_to_pdf(reader, pages, output_dir / out_name)


def preview_split(pdf_path: Path, mode: str, number: int = 0, spec: str = "") -> PreviewSummary:
    total = get_total_pages(pdf_path)
    if mode == "every_n":
        if number <= 0:
            raise ValueError("N페이지 단위는 1 이상이어야 합니다.")
        parts = (total + number - 1) // number
        return PreviewSummary(f"총 {total}페이지를 {number}페이지 단위로 분할 예정", f"생성 파일 수: {parts}개", total)
    if mode == "at_pages":
        cut_pages = parse_page_spec(spec, total)
        parts = len(_build_split_ranges(total, cut_pages))
        return PreviewSummary(f"총 {total}페이지를 기준 페이지 {', '.join(map(str, cut_pages))}로 분할 예정", f"생성 파일 수: {parts}개", total)
    raise ValueError("지원하지 않는 분할 모드입니다.")


def _build_split_ranges(total_pages: int, cut_pages_1based: list[int]) -> list[tuple[int, int]]:
    cuts = sorted(set(p for p in cut_pages_1based if 1 <= p <= total_pages))
    if not cuts:
        return [(1, total_pages)]
    ranges = []
    current_start = 1
    for cut in cuts:
        if cut > current_start:
            ranges.append((current_start, cut - 1))
        current_start = cut
    if current_start <= total_pages:
        ranges.append((current_start, total_pages))
    return [r for r in ranges if r[0] <= r[1]]


def run_split(pdf_path: Path, output_dir: Path, mode: str, number: int = 0, spec: str = "", zip_output: bool = False) -> list[Path]:
    total = get_total_pages(pdf_path)
    reader = _load_reader(pdf_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    ranges = []
    if mode == "every_n":
        if number <= 0:
            raise ValueError("N페이지 단위는 1 이상이어야 합니다.")
        start = 1
        while start <= total:
            end = min(start + number - 1, total)
            ranges.append((start, end))
            start = end + 1
    elif mode == "at_pages":
        cut_pages = parse_page_spec(spec, total)
        ranges = _build_split_ranges(total, cut_pages)
    else:
        raise ValueError("지원하지 않는 분할 모드입니다.")

    outputs = []
    base = _safe_stem(pdf_path.stem)
    for idx, (start, end) in enumerate(ranges, start=1):
        out_name = f"{base}_분할_{idx:03d}.pdf"
        out_path = write_pages_to_pdf(reader, range(start, end + 1), output_dir / out_name)
        outputs.append(out_path)

    if zip_output and outputs:
        zip_name = build_unique_path(output_dir / f"{base}_분할.zip")
        with zipfile.ZipFile(zip_name, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for f in outputs:
                zf.write(f, arcname=f.name)

    return outputs
