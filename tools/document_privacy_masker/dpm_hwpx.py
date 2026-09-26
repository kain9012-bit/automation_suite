"""문서 개인정보 마스킹 — 한글(hwpx) 읽기·쓰기.

hwpx 는 ZIP 안의 XML 이다. 본문 글자는 Contents/section*.xml 의 <hp:t> 안에 있다.
XML 을 통째로 다시 만들면(ElementTree 등) 이름공간 접두어·속성 순서가 바뀌어 한글에서
열리지 않을 수 있어서, 이 모듈은 XML 글자열을 그대로 두고 <hp:t> 안의 글자만 바꿔 끼운다.

  - 문단(<hp:p>)마다 글 조각을 만든다. 표 칸 안의 문단은 바깥 문단과 따로 센다.
  - 한 값이 글자 모양이 다른 두 run 에 나뉘어 있어도 같은 문단이면 이어서 찾는다.
  - 표(<hp:tbl>)는 칸 주소(cellAddr)로 행·열을 맞춰 표 머리글 검사를 한다.
  - 머리말·꼬리말·각주·메모도 section XML 안의 <hp:t> 이므로 같이 처리된다.
  - 미리보기 글(Preview/PrvText.txt)은 가린 글로 다시 만들고, 미리보기 그림
    (Preview/PrvImage.png)은 흰 그림으로 바꾼다. 원래 글이 그대로 남아 있기 때문이다.
  - 문서 정보(작성자·마지막 저장한 사람)는 비운다.
"""
from __future__ import annotations

import html
import re
import struct
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dpm_items import Edit, TableGrid, Unit

HWPX_MIMETYPE = b"application/hwp+zip"

_TAG_RE = re.compile(r"<(/?)([A-Za-z_][\w.-]*:)?([A-Za-z_][\w.-]*)((?:[^>\"']|\"[^\"]*\"|'[^']*')*?)(/?)>")
# <hp:t> 안에서 글자 대신 쓰이는 표시들
_INLINE_CHARS = {"tab": "\t", "lineBreak": "\n", "fwSpace": " ", "nbSpace": " ", "hyphen": "-"}


class HwpxError(Exception):
    pass


def check_hwpx(path: Path) -> None:
    """확장자만 hwpx 인 옛 hwp(OLE) 파일, 깨진 파일을 먼저 걸러 알려 준다."""
    head = path.read_bytes()[:8]
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        raise HwpxError("확장자는 hwpx 인데 실제로는 옛 한글(hwp) 형식입니다. 'HWP→HWPX 변환'으로 바꾼 뒤 넣어 주세요.")
    if not head.startswith(b"PK"):
        raise HwpxError("한글(hwpx) 파일이 아니거나 손상된 파일입니다.")
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            if "mimetype" in names and z.read("mimetype").strip() != HWPX_MIMETYPE:
                raise HwpxError("한글(hwpx) 형식이 아닙니다.")
            if not any(n.startswith("Contents/section") for n in names):
                raise HwpxError("한글 본문(section)을 찾지 못했습니다.")
            if any(n.startswith("META-INF/") and "encrypt" in n.lower() for n in names):
                raise HwpxError("암호가 걸린 한글 문서는 처리할 수 없습니다.")
    except zipfile.BadZipFile as exc:
        raise HwpxError("한글(hwpx) 파일이 손상되었습니다.") from exc


# ---------------------------------------------------------------- 읽기

@dataclass
class _Piece:
    """<hp:t> 안의 글자 덩어리 하나. XML 원문에서의 위치와 풀어 쓴 글자."""
    part: str
    xml_start: int
    xml_end: int
    text: str


class HwpxDoc:
    def __init__(self, path: Path):
        self.path = path
        with zipfile.ZipFile(path) as z:
            self.infos = z.infolist()
            self.data = {i.filename: z.read(i.filename) for i in self.infos}
        self.pieces: list[_Piece] = []
        self.units: list[Unit] = []
        self.tables: list[TableGrid] = []
        self.image_count = sum(1 for n in self.data if n.startswith("BinData/"))
        self.warnings: list[str] = []
        # 확인 화면의 글 미리보기용: 문서 순서대로 문단·표
        self.blocks: list[dict] = []
        self._parse()

    # 본문 XML: Contents/ 아래에서 <hp:t> 가 있는 것(section, masterpage 등)
    def text_parts(self) -> list[str]:
        out = []
        for name in self.data:
            if name.startswith("Contents/") and name.endswith(".xml") and name != "Contents/header.xml":
                if b"<hp:t" in self.data[name] or b":t>" in self.data[name]:
                    out.append(name)
        return sorted(out, key=lambda n: (not n.startswith("Contents/section"), _num(n), n))

    def _parse(self) -> None:
        para_no = 0
        table_no = 0
        for part in self.text_parts():
            xml = self.data[part].decode("utf-8")
            section_label = _part_label(part)
            # 문단 스택: 각 문단의 (글자, 위치) 목록
            stack: list[dict] = []
            # 표 스택: 표마다 {rows: {(r,c): [문단 unit…]}, cell: 현재 칸 정보}
            tstack: list[dict] = []
            in_t = 0
            pos = 0
            for m in _TAG_RE.finditer(xml):
                # 태그 앞의 글자
                if in_t and stack and m.start() > pos:
                    raw = xml[pos:m.start()]
                    text = html.unescape(raw)
                    idx = len(self.pieces)
                    self.pieces.append(_Piece(part, pos, m.start(), text))
                    for k, ch in enumerate(text):
                        stack[-1]["chars"].append((ch, (idx, k)))
                pos = m.end()
                closing, local, attrs, selfclose = m.group(1), m.group(3), m.group(4), m.group(5)
                if local == "p":
                    if not closing and not selfclose:
                        stack.append({"chars": [], "xml_start": m.start()})
                    elif closing and stack:
                        para = stack.pop()
                        para_no += 1
                        chars = para["chars"]
                        in_cell = bool(tstack) and tstack[-1].get("cell") is not None \
                            and tstack[-1]["cell"]["depth"] == len(stack)
                        if in_cell:
                            where = f"{section_label} 표 {tstack[-1]['no']}"
                        else:
                            where = f"{section_label} {para_no}번째 문단"
                        unit = Unit(
                            uid=f"{part}#p{para_no}",
                            text="".join(ch for ch, _ in chars),
                            positions=[p for _, p in chars],
                            where=where,
                            extra={"part": part},
                        )
                        if unit.text.strip():
                            self.units.append(unit)
                            if not in_cell:
                                self.blocks.append({"type": "p", "unit": unit})
                        if in_cell:
                            tstack[-1]["cell"]["units"].append(unit)
                        # 문단이 닫히면 그 문단 안의 글자는 바깥 문단에 속하지 않는다.
                elif local == "t":
                    if not closing and not selfclose:
                        in_t += 1
                    elif closing:
                        in_t = max(0, in_t - 1)
                elif in_t and stack and local in _INLINE_CHARS:
                    stack[-1]["chars"].append((_INLINE_CHARS[local], None))
                elif local == "tbl":
                    if not closing and not selfclose:
                        table_no += 1
                        tstack.append({"no": table_no, "cells": {}, "cell": None, "spans": {}})
                    elif closing and tstack:
                        t = tstack.pop()
                        grid = _grid(t, f"{section_label} 표 {t['no']}", part)
                        self.tables.append(grid)
                        self.blocks.append({"type": "table", "grid": grid, "spans": t["spans"]})
                elif local == "tc" and tstack:
                    if not closing and not selfclose:
                        tstack[-1]["cell"] = {"units": [], "addr": None, "depth": len(stack)}
                    elif closing and tstack[-1]["cell"] is not None:
                        cell = tstack[-1]["cell"]
                        if cell["addr"] is not None:
                            tstack[-1]["cells"][cell["addr"]] = cell["units"]
                            if cell.get("span"):
                                tstack[-1]["spans"][cell["addr"]] = cell["span"]
                        tstack[-1]["cell"] = None
                elif local == "cellAddr" and tstack and tstack[-1]["cell"] is not None:
                    col = re.search(r'colAddr="(\d+)"', attrs)
                    row = re.search(r'rowAddr="(\d+)"', attrs)
                    if col and row:
                        tstack[-1]["cell"]["addr"] = (int(row.group(1)), int(col.group(1)))
                elif local == "cellSpan" and tstack and tstack[-1]["cell"] is not None:
                    cs = re.search(r'colSpan="(\d+)"', attrs)
                    rs = re.search(r'rowSpan="(\d+)"', attrs)
                    span = (int(rs.group(1)) if rs else 1, int(cs.group(1)) if cs else 1)
                    if span != (1, 1):
                        tstack[-1]["cell"]["span"] = span
            if stack:
                self.warnings.append(f"{part}: 문단 구조를 끝까지 읽지 못했습니다.")

    def view(self) -> tuple[list[dict], dict]:
        """확인 화면의 글 미리보기: 문서 순서대로 문단·표 글과, 글자 위치 → [블록, 행, 열, 글자] 표.
        문단은 행·열이 -1 이다. 표에서 병합으로 가려진 칸은 None."""
        blocks: list[dict] = []
        spot: dict = {}
        for b_no, block in enumerate(self.blocks):
            if block["type"] == "p":
                unit = block["unit"]
                blocks.append({"type": "p", "text": unit.text})
                for i, p in enumerate(unit.positions):
                    if p is not None:
                        spot.setdefault(p, [b_no, -1, -1, i])
                continue
            rows = []
            for r, row in enumerate(block["grid"].cells):
                out = []
                for c, cell in enumerate(row):
                    if cell is None:
                        out.append(None)
                        continue
                    rs, cs = block["spans"].get((r, c), (1, 1))
                    out.append({"text": cell.text, "rs": rs, "cs": cs})
                    for i, p in enumerate(cell.positions):
                        if p is not None:
                            spot.setdefault(p, [b_no, r, c, i])
                rows.append(out)
            blocks.append({"type": "table", "rows": rows})
        return blocks, spot

    # ------------------------------------------------------------ 쓰기

    def write(self, edits: list[Edit], out_path: Path) -> dict:
        by_piece: dict[int, dict[int, str]] = {}
        for e in edits:
            if not isinstance(e.position, tuple):
                continue
            idx, k = e.position
            by_piece.setdefault(idx, {})[k] = e.new_char
        changed_parts: dict[str, list[tuple[int, int, str]]] = {}
        for idx, changes in by_piece.items():
            piece = self.pieces[idx]
            chars = list(piece.text)
            for k, ch in changes.items():
                if 0 <= k < len(chars):
                    chars[k] = ch
            new_text = "".join(chars)
            changed_parts.setdefault(piece.part, []).append((piece.xml_start, piece.xml_end, _escape(new_text)))

        new_data = dict(self.data)
        for part, repl in changed_parts.items():
            xml = self.data[part].decode("utf-8")
            # 바뀐 문단의 줄 배치 정보는 한글이 다시 계산하도록 지운다(글자 수가 바뀐 경우 대비).
            ops = list(repl) + [(a, b, "") for a, b in _lineseg_spans(xml, [r[0] for r in repl])]
            for start, end, text in sorted(ops, reverse=True):
                xml = xml[:start] + text + xml[end:]
            new_data[part] = xml.encode("utf-8")

        report = {"metadata_cleared": [], "preview_text": False, "preview_image": False}
        # 문서 정보: 작성자·마지막 저장자
        for name in list(new_data):
            if name.endswith("content.hpf"):
                hpf = new_data[name].decode("utf-8")
                for key in ("creator", "lastsaveby"):
                    pat = re.compile(rf'(<opf:meta name="{key}"[^>]*>)([^<]*)(</opf:meta>)')
                    if pat.search(hpf) and pat.search(hpf).group(2).strip():
                        report["metadata_cleared"].append(key)
                    hpf = pat.sub(r"\1\3", hpf)
                new_data[name] = hpf.encode("utf-8")
        # 미리보기 글: 가린 뒤의 본문으로 다시 만든다.
        if "Preview/PrvText.txt" in new_data:
            new_data["Preview/PrvText.txt"] = self._preview_text(edits).encode("utf-8")
            report["preview_text"] = True
        # 미리보기 그림: 원래 글이 그림으로 남아 있어 흰 그림으로 바꾼다.
        for name in list(new_data):
            if name.lower().startswith("preview/") and name.lower().endswith(".png"):
                new_data[name] = _blank_png_like(new_data[name])
                report["preview_image"] = True

        tmp = out_path.with_name(out_path.name + ".tmp")
        with zipfile.ZipFile(tmp, "w") as z:
            for info in self.infos:
                zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
                zi.external_attr = info.external_attr
                # mimetype 은 압축하지 않고 맨 앞에 둔다(규격).
                zi.compress_type = zipfile.ZIP_STORED if info.filename == "mimetype" else info.compress_type
                z.writestr(zi, new_data[info.filename])
        tmp.replace(out_path)
        return report

    def _preview_text(self, edits: list[Edit]) -> str:
        changes = {e.position: e.new_char for e in edits}
        lines = []
        for unit in self.units:
            out = []
            for ch, p in zip(unit.text, unit.positions):
                out.append(changes.get(p, ch) if p is not None else ch)
            lines.append("".join(out))
        text = "\r\n".join(lines)
        return text[:4096]


def _grid(t: dict, where: str, part: str) -> TableGrid:
    cells = t["cells"]
    if not cells:
        return TableGrid(tid=f"{part}#t{t['no']}", where=where, cells=[])
    n_rows = max(r for r, _ in cells) + 1
    n_cols = max(c for _, c in cells) + 1
    grid: list[list[Optional[Unit]]] = [[None] * n_cols for _ in range(n_rows)]
    for (r, c), units in cells.items():
        if not units:
            continue
        text_parts, positions = [], []
        for i, u in enumerate(units):
            if i:
                text_parts.append("\n")
                positions.append(None)
            text_parts.append(u.text)
            positions.extend(u.positions)
        grid[r][c] = Unit(uid=f"{part}#t{t['no']}r{r}c{c}", text="".join(text_parts), positions=positions,
                          where=where, extra={"part": part})
    return TableGrid(tid=f"{part}#t{t['no']}", where=where, cells=grid)


def _num(name: str) -> int:
    m = re.search(r"(\d+)", name)
    return int(m.group(1)) if m else 0


def _part_label(part: str) -> str:
    if part.startswith("Contents/section"):
        return f"{_num(part) + 1}구역"
    if "master" in part.lower():
        return "바탕쪽"
    return Path(part).stem


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _lineseg_spans(xml: str, positions: list[int]) -> list[tuple[int, int]]:
    """바뀐 글자가 들어 있는 문단의 <hp:linesegarray>…</hp:linesegarray> 위치(원래 XML 기준)."""
    spans = set()
    for pos in set(positions):
        end_p = xml.find("</hp:p>", pos)
        if end_p < 0:
            continue
        seg_start = xml.find("<hp:linesegarray>", pos, end_p + 200)
        if seg_start < 0 or seg_start > end_p:
            continue
        seg_end = xml.find("</hp:linesegarray>", seg_start)
        if seg_end < 0:
            continue
        spans.add((seg_start, seg_end + len("</hp:linesegarray>")))
    return sorted(spans)


def _blank_png_like(data: bytes) -> bytes:
    """같은 크기의 흰 PNG 를 만든다(표준 라이브러리만 사용)."""
    width, height = 1, 1
    if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        width, height = struct.unpack(">II", data[16:24])
    width, height = max(1, min(width, 2000)), max(1, min(height, 3000))
    raw = b"".join(b"\x00" + b"\xff" * (width * 3) for _ in range(height))

    def chunk(tag: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def metadata_text(path: Path) -> str:
    """다시 검사할 때 쓰는 문서 정보·미리보기 글."""
    out = []
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if name.endswith("content.hpf") or name == "Preview/PrvText.txt":
                out.append(z.read(name).decode("utf-8", "replace"))
    return "\n".join(out)
