"""문서 개인정보 마스킹 — 문서 형식과 상관없이 쓰는 '찾은 항목' 묶음.

hwpx·PDF 모두 문서를 '글 조각(unit)' 들로 읽는다. 조각마다
  text      : 사람이 읽는 글
  positions : 글자 하나하나가 문서 안 어디에 있는지(형식마다 다른 열쇠). 줄바꿈처럼 문서에
              실제 글자가 없는 자리는 None.
을 가진다. 표는 칸마다 같은 방식으로 따로 읽는다.

같은 글자를 문단 검사와 표 검사가 둘 다 찾을 수 있어서, 항목은 '문서 안 글자 위치의 모음'으로
합친다. 같은 위치를 두 종류로 찾으면 우선순위가 높은 종류 하나만 남긴다.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Hashable, Optional

from dpm_detect import _PRIORITY, Finding, detect_table, detect_text
from dpm_kinds import FIXED_CODES, KEEP, KINDS, MASK_ALL, label_of
from dpm_mask import masked_text


@dataclass
class Unit:
    """문서 안의 글 한 덩어리(문단·PDF 한 쪽 등)."""
    uid: str
    text: str
    positions: list[Optional[Hashable]]
    where: str                      # 사람이 읽는 위치: '1쪽', '3번째 문단', '표 2 (2행 3열)'
    extra: dict = field(default_factory=dict)


@dataclass
class TableGrid:
    """문서 안의 표 하나. cells[r][c] 는 Unit 또는 None(병합 등으로 빈 칸)."""
    tid: str
    where: str
    cells: list[list[Optional[Unit]]]


@dataclass
class Item:
    kind: str
    positions: list[Optional[Hashable]]   # text 의 글자마다 문서 안 위치(줄바꿈 등 없는 자리는 None)
    text: str
    confidence: float
    reasons: list[str]
    where: str
    context: str
    unit_id: str
    extra: dict = field(default_factory=dict)

    @property
    def keys(self) -> list[Hashable]:
        return [p for p in self.positions if p is not None]

    @property
    def id(self) -> str:
        keys = self.keys
        key = f"{self.unit_id}|{self.kind}|{keys[0]!r}|{keys[-1]!r}|{self.text}"
        return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]

    def to_dict(self) -> dict[str, Any]:
        info = KINDS.get(self.kind)
        return {
            "id": self.id,
            "kind": self.kind,
            "label": label_of(self.kind),
            "text": self.text,
            "confidence": round(self.confidence, 2),
            "reasons": list(self.reasons),
            "where": self.where,
            "context": self.context,
            "fixed": self.kind in FIXED_CODES,
            "action": info.default_action if info else MASK_ALL,
            **{k: v for k, v in self.extra.items() if k in ("page", "rects")},
        }


def _context(text: str, start: int, end: int, width: int = 24) -> str:
    left = text[max(0, start - width):start].replace("\n", " ")
    right = text[end:end + width].replace("\n", " ")
    return f"{left}【{text[start:end]}】{right}".strip()


def _item_from(unit: Unit, f: Finding, where: str | None = None) -> Optional[Item]:
    pos = list(unit.positions[f.start:f.end])
    if not any(p is not None for p in pos):
        return None
    return Item(
        kind=f.kind, positions=pos, text=unit.text[f.start:f.end], confidence=f.confidence,
        reasons=list(f.reasons), where=where or unit.where, context=_context(unit.text, f.start, f.end),
        unit_id=unit.uid, extra=dict(unit.extra),
    )


def find_items(units: list[Unit], tables: list[TableGrid]) -> list[Item]:
    """문단과 표에서 찾은 것을 합쳐 항목 목록을 만든다."""
    raw: list[Item] = []
    for unit in units:
        for f in detect_text(unit.text):
            item = _item_from(unit, f)
            if item:
                raw.append(item)
    for table in tables:
        rows = [[(cell.text if cell else "") for cell in row] for row in table.cells]
        for cf in detect_table(rows):
            cell = table.cells[cf.row][cf.col]
            if cell is None:
                continue
            where = f"{table.where} ({cf.row + 1}행 {cf.col + 1}열)"
            item = _item_from(cell, cf.finding, where)
            if item:
                raw.append(item)
    return _merge_items(raw)


def _merge_items(items: list[Item]) -> list[Item]:
    """같은 글자를 여러 번 찾은 것을 정리한다.

    - 같은 종류: 더 넓게 찾은 것 하나를 남기고 이유를 합친다.
    - 다른 종류: 우선순위(법정 7종 먼저) → 신뢰도 → 길이 순으로 하나만 남긴다.
    """
    ranked = sorted(items, key=lambda i: (-_PRIORITY.get(i.kind, 0), -len(i.keys), -i.confidence))
    kept: list[Item] = []
    owner: dict = {}
    for it in ranked:
        keys = set(it.keys)
        hit = {id(owner[k]): owner[k] for k in keys if k in owner}
        if not hit:
            kept.append(it)
            for k in keys:
                owner[k] = it
            continue
        for other in hit.values():
            if other.kind == it.kind:
                if "행" in it.where and "행" not in other.where and set(other.keys) == keys:
                    other.where = it.where   # 표 칸 위치가 더 알아보기 쉽다
                other.confidence = max(other.confidence, it.confidence)
                for r in it.reasons:
                    if r not in other.reasons:
                        other.reasons.append(r)
    return sorted(kept, key=lambda i: (i.unit_id, str(i.keys[0])))


def items_for_terms(units: list[Unit], tables: list[TableGrid], terms: list[dict]) -> list[Item]:
    """확인 화면에서 사용자가 '직접 추가'한 글자를 문서 전체에서 찾는다."""
    out: list[Item] = []
    all_units = list(units) + [c for t in tables for row in t.cells for c in row if c is not None]
    seen: set = set()
    for term in terms:
        value = str(term.get("text") or "").strip()
        kind = str(term.get("kind") or "CUSTOM")
        if len(value) < 2:
            continue
        for unit in all_units:
            for m in re.finditer(re.escape(value), unit.text):
                pos = list(unit.positions[m.start():m.end()])
                key = tuple(p for p in pos if p is not None)
                if not key or key in seen:
                    continue
                seen.add(key)
                out.append(Item(kind=kind if kind in KINDS else "CUSTOM", positions=pos, text=value,
                                confidence=1.0, reasons=["직접 추가"], where=unit.where,
                                context=_context(unit.text, m.start(), m.end()), unit_id=unit.uid,
                                extra=dict(unit.extra)))
    return out


def combine_terms(items: list[Item], term_items: list[Item]) -> list[Item]:
    """'직접 추가'한 글자를 찾은 항목에 붙인다.

    이미 찾은 항목 하나 안에 통째로 들어가는 것은 빼고(목록에 이미 있으니 그 항목의 처리 방식을
    바꾸면 된다), 걸치거나 새로운 자리만 따로 항목으로 둔다."""
    out = list(items)
    for term in term_items:
        keys = set(term.keys)
        if any(keys <= set(it.keys) for it in items):
            continue
        out.append(term)
    return out


@dataclass
class Edit:
    """글자 위치 하나를 어떻게 바꿀지. new_char 가 '' 이면 그 글자를 지운다."""
    position: Hashable
    new_char: str


def plan_edits(items: list[Item], decisions: dict[str, str]) -> tuple[list[Edit], list[Item]]:
    """항목별 처리 방식대로 글자 단위 수정 목록을 만든다. (수정 목록, 실제로 가린 항목)"""
    edits: dict[Hashable, str] = {}
    done: list[Item] = []
    for it in items:
        action = decisions.get(it.id) or (KINDS[it.kind].default_action if it.kind in KINDS else MASK_ALL)
        if action == KEEP:
            continue
        new = masked_text(it.kind, it.text, action)
        if new == it.text:
            continue
        done.append(it)
        if len(new) == len(it.text):
            for pos, old_ch, new_ch in zip(it.positions, it.text, new):
                if pos is not None and old_ch != new_ch and not _locked(edits.get(pos)):
                    edits[pos] = new_ch
        else:
            # 글자 수가 달라지는 '종류로 바꿈': 첫 글자 자리에 통째로 넣고 나머지는 지운다.
            keys = it.keys
            if not _locked(edits.get(keys[0])):
                edits[keys[0]] = new
            for pos in keys[1:]:
                if not _locked(edits.get(pos)):
                    edits[pos] = ""
    return [Edit(p, c) for p, c in edits.items()], done


def _locked(value: Optional[str]) -> bool:
    """이미 '종류로 바꿈'이 차지한 자리(지운 글자·통째로 넣은 글자)는 겹치는 다른 항목이 덮지 않는다."""
    return value is not None and len(value) != 1


def leftover_check(masked: list[Item], kept: list[Item], after_units: list[Unit],
                   after_tables: list[TableGrid]) -> dict[str, Any]:
    """다시 연 결과 문서에서
      - 가린 값이 원래 모양대로 남아 있는지(사람이 '가리지 않음'으로 고른 같은 값은 제외)
      - 법정 7종(주민번호·계좌 등)이 가려지지 않은 채 보이는지
    를 확인한다."""
    texts = [u.text for u in after_units]
    texts += [c.text for t in after_tables for row in t.cells for c in row if c]
    flat = re.sub(r"\s+", "", "\n".join(texts))
    kept_values = {re.sub(r"\s+", "", it.text) for it in kept}
    remained, seen = [], set()
    for it in masked:
        value = re.sub(r"\s+", "", it.text)
        if len(value) >= 2 and value in flat and value not in kept_values and value not in seen:
            seen.add(value)
            remained.append({"label": label_of(it.kind), "text": it.text, "where": it.where})
    fixed_left, seen = [], set()
    for text in texts:
        for f in detect_text(text):
            if f.kind in FIXED_CODES and not re.search(r"[*＊■●]", f.text):
                value = re.sub(r"\s+", "", f.text)
                if value in kept_values or value in seen:
                    continue
                seen.add(value)
                fixed_left.append({"label": label_of(f.kind), "text": f.text})
    return {"ok": not remained and not fixed_left, "remained": remained, "fixed_left": fixed_left}
