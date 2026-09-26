"""문서 개인정보 마스킹 — PDF 읽기·쓰기(PyMuPDF).

- 글자를 하나하나 위치(사각형)와 함께 읽는다(rawdict). 한 쪽을 글 조각 하나로 본다.
- 표는 PyMuPDF 의 표 찾기(find_tables)로 칸 사각형을 얻고, 칸 안에 든 글자로 칸 글을 만든다.
- 가릴 때는 검은 사각형을 '그리는' 것이 아니라 그 자리의 글자를 실제로 지운다
  (add_redact_annot + apply_redactions, Tiny PDF Editor 의 방식). 사각형만 덮으면
  복사·붙여넣기로 글자가 그대로 읽히기 때문이다.
- 일부 가림(010-****-5678)은 바뀌는 글자 자리만 지운다. 남기는 글자는 원래 모양 그대로다.
- 그림·선(표 테두리)은 지우지 않는다.
- 문서 정보(작성자 등)·XMP·목차 제목·메모 주석·첨부 파일도 정리하고, 저장할 때 쓰이지 않는
  옛 내용까지 정리(garbage=4)해 지운 글자가 파일 안에 남지 않게 한다.
- 글자가 없는 쪽(스캔본)은 처리하지 못한다고 알린다.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

# 앱은 도구가 표준출력에 쓴 글을 결과(JSON)로 읽는다. PyMuPDF 는 표 찾기(find_tables)를 처음 쓸 때
# 'Consider using the pymupdf_layout package…' 안내를, MuPDF 경고는 평소 표준출력에 찍는다.
# 그 한 줄이 결과 앞에 붙으면 앱이 결과를 읽지 못해 화면이 멈춘다. 그래서 안내는 끄고 경고는 오류 출력으로 보낸다.
os.environ.setdefault("PYMUPDF_SUGGEST_LAYOUT_ANALYZER", "0")

import pymupdf  # noqa: E402

if hasattr(pymupdf, "no_recommend_layout"):
    pymupdf.no_recommend_layout()
try:
    pymupdf.set_messages(stream=sys.stderr)
except Exception:
    pass

from dpm_items import Edit, TableGrid, Unit


class PdfError(Exception):
    pass


class PdfDoc:
    def __init__(self, path: Path):
        self.path = path
        try:
            self.doc = pymupdf.open(path)
        except Exception as exc:
            raise PdfError(f"PDF 를 열지 못했습니다: {exc}") from exc
        if self.doc.needs_pass or self.doc.is_encrypted:
            raise PdfError("암호가 걸린 PDF 는 처리할 수 없습니다.")
        self.units: list[Unit] = []
        self.tables: list[TableGrid] = []
        self.char_rect: dict[tuple[int, int], tuple[float, float, float, float]] = {}
        self.char_text: dict[tuple[int, int], str] = {}
        self.page_chars: dict[int, list[tuple[tuple[int, int], tuple[float, float, float, float]]]] = {}
        self.scanned_pages: list[int] = []
        self.warnings: list[str] = []
        self._parse()

    def _parse(self) -> None:
        for pno, page in enumerate(self.doc):
            raw = page.get_text("rawdict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_MEDIABOX_CLIP)
            chars: list[tuple[str, Optional[tuple[int, int]]]] = []
            k = 0
            for block in raw.get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        for ch in span.get("chars", []):
                            c = ch.get("c", "")
                            if not c:
                                continue
                            key = (pno, k)
                            k += 1
                            self.char_rect[key] = tuple(ch["bbox"])
                            self.char_text[key] = c
                            self.page_chars.setdefault(pno, []).append((key, tuple(ch["bbox"])))
                            chars.append((c, key))
                    chars.append(("\n", None))
                chars.append(("\n", None))
            text = "".join(c for c, _ in chars)
            if not text.strip():
                if page.get_images():
                    self.scanned_pages.append(pno + 1)
                continue
            self.units.append(Unit(
                uid=f"p{pno + 1}", text=text, positions=[p for _, p in chars],
                where=f"{pno + 1}쪽", extra={"page": pno + 1},
            ))
            self._tables_on_page(page, pno)

    def _tables_on_page(self, page, pno: int) -> None:
        try:
            found = page.find_tables()
        except Exception:
            return
        for tno, tab in enumerate(getattr(found, "tables", []) or [], start=1):
            rows_out: list[list[Optional[Unit]]] = []
            for r, row in enumerate(tab.rows):
                cells_out: list[Optional[Unit]] = []
                for c, cell in enumerate(row.cells):
                    if cell is None:
                        cells_out.append(None)
                        continue
                    x0, y0, x1, y1 = cell
                    inside = [
                        (key, rect) for key, rect in self.page_chars.get(pno, [])
                        if x0 - 0.5 <= (rect[0] + rect[2]) / 2 <= x1 + 0.5
                        and y0 - 0.5 <= (rect[1] + rect[3]) / 2 <= y1 + 0.5
                    ]
                    inside.sort(key=lambda kr: kr[0][1])
                    unit_text, positions = [], []
                    prev_y = None
                    for key, rect in inside:
                        if prev_y is not None and abs(rect[1] - prev_y) > 2:
                            unit_text.append("\n")
                            positions.append(None)
                        prev_y = rect[1]
                        unit_text.append(self.char_text[key])
                        positions.append(key)
                    cells_out.append(Unit(uid=f"p{pno + 1}t{tno}r{r}c{c}", text="".join(unit_text),
                                          positions=positions, where=f"{pno + 1}쪽 표 {tno}",
                                          extra={"page": pno + 1}))
                rows_out.append(cells_out)
            self.tables.append(TableGrid(tid=f"p{pno + 1}t{tno}", where=f"{pno + 1}쪽 표 {tno}", cells=rows_out))

    # ------------------------------------------------------------ 쓰기

    def write(self, edits: list[Edit], out_path: Path, manual_boxes: list[dict] | None = None) -> dict:
        """바뀌는 글자 자리를 실제로 지운다. manual_boxes: [{page, x0, y0, x1, y1}] 사용자가 직접 그린 영역."""
        by_page: dict[int, list[tuple[float, float, float, float]]] = {}
        for e in edits:
            rect = self.char_rect.get(e.position)
            if rect is None:
                continue
            by_page.setdefault(e.position[0], []).append(rect)
        for box in manual_boxes or []:
            try:
                pno = int(box["page"]) - 1
                by_page.setdefault(pno, []).append((float(box["x0"]), float(box["y0"]), float(box["x1"]), float(box["y1"])))
            except (KeyError, TypeError, ValueError):
                continue

        report = {"redacted": 0, "metadata_cleared": False, "annotations_removed": 0,
                  "attachments_removed": 0, "toc_titles_masked": 0}
        for pno, rects in by_page.items():
            page = self.doc[pno]
            for rect in _merge_rects(rects):
                page.add_redact_annot(pymupdf.Rect(*_shrink(rect)), fill=(0, 0, 0))
                report["redacted"] += 1
            _apply(page)

        # 메모 주석(스티커 메모·자유 글 등)은 사본에서 뺀다. 링크·입력칸은 둔다.
        for page in self.doc:
            for annot in list(page.annots() or []):
                if annot.type[0] in (pymupdf.PDF_ANNOT_TEXT, pymupdf.PDF_ANNOT_FREE_TEXT,
                                     pymupdf.PDF_ANNOT_POPUP, pymupdf.PDF_ANNOT_FILE_ATTACHMENT):
                    page.delete_annot(annot)
                    report["annotations_removed"] += 1
        # 첨부 파일
        try:
            names = self.doc.embfile_names()
            for name in names:
                self.doc.embfile_del(name)
            report["attachments_removed"] = len(names)
        except Exception:
            pass
        # 목차(책갈피) 제목에 이름·번호가 있으면 가린다.
        try:
            from dpm_detect import detect_text
            from dpm_mask import masked_text
            from dpm_kinds import KINDS
            toc = self.doc.get_toc(simple=False)
            changed = False
            for entry in toc:
                title = entry[1]
                found = detect_text(title)
                for f in sorted(found, key=lambda x: -x.start):
                    new = masked_text(f.kind, f.text, KINDS[f.kind].default_action)
                    title = title[:f.start] + new + title[f.end:]
                if found:
                    entry[1] = title
                    changed = True
                    report["toc_titles_masked"] += 1
            if changed:
                self.doc.set_toc(toc)
        except Exception:
            pass
        # 문서 정보·XMP
        meta = self.doc.metadata or {}
        if any((meta.get(k) or "").strip() for k in ("author", "creator", "producer", "title", "subject", "keywords")):
            report["metadata_cleared"] = True
        self.doc.set_metadata({})
        try:
            self.doc.del_xml_metadata()
        except Exception:
            pass

        tmp = out_path.with_name(out_path.name + ".tmp")
        self.doc.save(tmp, garbage=4, deflate=True, clean=True)
        self.doc.close()
        tmp.replace(out_path)
        return report

    def close(self) -> None:
        try:
            self.doc.close()
        except Exception:
            pass


def _apply(page) -> None:
    """글자만 지우고 그림·선은 둔다. 옛 PyMuPDF 는 graphics 인자가 없어 나눠 부른다."""
    kwargs = {"images": getattr(pymupdf, "PDF_REDACT_IMAGE_NONE", 0)}
    line_art_none = getattr(pymupdf, "PDF_REDACT_LINE_ART_NONE", None)
    if line_art_none is not None:
        kwargs["graphics"] = line_art_none
    try:
        page.apply_redactions(**kwargs)
    except TypeError:
        kwargs.pop("graphics", None)
        page.apply_redactions(**kwargs)


def _merge_rects(rects: list[tuple[float, float, float, float]]) -> list[tuple[float, float, float, float]]:
    """같은 줄에서 붙어 있는 글자 사각형을 하나로 합친다."""
    rects = sorted(rects, key=lambda r: (round(r[1], 1), r[0]))
    out: list[list[float]] = []
    for r in rects:
        if out:
            last = out[-1]
            same_line = abs(last[1] - r[1]) < 1.5 and abs(last[3] - r[3]) < 1.5
            if same_line and r[0] - last[2] < 1.0:
                last[2] = max(last[2], r[2])
                last[1] = min(last[1], r[1])
                last[3] = max(last[3], r[3])
                continue
        out.append(list(r))
    return [tuple(r) for r in out]


def _shrink(rect: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """이웃 글자까지 지워지지 않도록 가로 양끝을 조금 들인다."""
    x0, y0, x1, y1 = rect
    inset = min(0.8, (x1 - x0) * 0.12)
    return (x0 + inset, y0, x1 - inset, y1)
