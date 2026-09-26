"""문서 개인정보 마스킹 — 앱(사이드카)이 부르는 입구.

두 단계로 쓴다.
  1) analyze_file(path)            : 문서를 읽어 찾은 개인정보 목록을 돌려준다(파일은 만들지 않음).
  2) apply_file(path, decisions…)  : 사람이 확인한 결정대로 가린 사본을 만들고, 사본을 다시 열어 검사한다.

분석과 적용 사이에 문서를 다시 읽어 같은 규칙으로 찾기 때문에 항목 id 가 그대로 맞는다.
원본 파일은 절대 고치지 않는다. 사본 이름: '원본이름_마스킹.hwpx' / '원본이름_마스킹.pdf'
(같은 이름이 있으면 '(1)' 을 붙인다).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Optional

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from dpm_items import find_items, items_for_terms, leftover_check, plan_edits  # noqa: E402
from dpm_kinds import ACTION_LABELS, FIXED_CODES, KINDS  # noqa: E402

SUPPORTED = (".hwpx", ".pdf")


def _open(path: Path):
    ext = path.suffix.lower()
    if ext == ".hwpx":
        from dpm_hwpx import HwpxDoc, check_hwpx
        check_hwpx(path)
        return HwpxDoc(path)
    if ext == ".pdf":
        from dpm_pdf import PdfDoc
        return PdfDoc(path)
    if ext == ".hwp":
        raise ValueError("옛 한글(hwp) 파일은 'HWP→HWPX 변환'으로 hwpx 로 바꾼 뒤 넣어 주세요.")
    raise ValueError(f"지원하지 않는 형식입니다: {path.suffix} (hwpx, pdf 만 됩니다)")


def _warnings(doc) -> list[str]:
    out = list(getattr(doc, "warnings", []))
    scanned = getattr(doc, "scanned_pages", [])
    if scanned:
        pages = ", ".join(str(p) for p in scanned[:10]) + (" …" if len(scanned) > 10 else "")
        out.append(f"글자가 없는 쪽(스캔·그림)이 있어 처리하지 못했습니다: {pages}쪽. 눈으로 확인해 주세요.")
    images = getattr(doc, "image_count", 0)
    if images:
        out.append(f"문서에 그림 {images}개가 있습니다. 그림 속 글자·도장·사진은 찾지 못하니 눈으로 확인해 주세요.")
    return out


def analyze_file(path: str | Path) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    doc = _open(path)
    try:
        if not doc.units:
            if getattr(doc, "scanned_pages", None):
                raise ValueError("글자가 없는 PDF(스캔본)입니다. 이 도구는 스캔 문서를 처리하지 않습니다.")
            raise ValueError("문서에서 글자를 찾지 못했습니다.")
        items = find_items(doc.units, doc.tables)
        dicts = [it.to_dict() for it in items]
        if hasattr(doc, "char_rect"):
            # PDF: 미리보기에서 칠해 보여 줄 자리(쪽 번호와 사각형)
            from dpm_pdf import _merge_rects
            for it, d in zip(items, dicts):
                rects = [doc.char_rect[k] for k in it.keys if k in doc.char_rect]
                d["page"] = it.keys[0][0] + 1 if it.keys else None
                d["rects"] = [[round(v, 1) for v in r] for r in _merge_rects(rects)]
        return {
            "file": str(path),
            "name": path.name,
            "format": path.suffix.lower().lstrip("."),
            "items": dicts,
            "counts": _counts(items),
            "warnings": _warnings(doc),
            "kinds": {code: {"label": k.label, "fixed": k.fixed, "action": k.default_action} for code, k in KINDS.items()},
            "actions": ACTION_LABELS,
        }
    finally:
        if hasattr(doc, "close"):
            doc.close()


def _counts(items) -> dict[str, int]:
    out: dict[str, int] = {}
    for it in items:
        out[it.kind] = out.get(it.kind, 0) + 1
    return out


def _output_path(path: Path, output_dir: Optional[Path]) -> Path:
    folder = output_dir or path.parent
    folder.mkdir(parents=True, exist_ok=True)
    base = folder / f"{path.stem}_마스킹{path.suffix.lower()}"
    if not base.exists():
        return base
    n = 1
    while (folder / f"{path.stem}_마스킹({n}){path.suffix.lower()}").exists():
        n += 1
    return folder / f"{path.stem}_마스킹({n}){path.suffix.lower()}"


def apply_file(
    path: str | Path,
    decisions: Optional[dict[str, str]] = None,
    extra_terms: Optional[list[dict]] = None,
    manual_boxes: Optional[list[dict]] = None,
    output_dir: Optional[str | Path] = None,
    log: Optional[Callable[[str], None]] = None,
) -> dict[str, Any]:
    """decisions: {항목 id: 처리 방식}. 적지 않은 항목은 기본 처리 방식을 쓴다.
    법정 7종은 '그대로 둠'을 주어도 가린다."""
    say = log or (lambda _t: None)
    path = Path(path).expanduser().resolve()
    decisions = dict(decisions or {})
    doc = _open(path)
    items = find_items(doc.units, doc.tables)
    items += items_for_terms(doc.units, doc.tables, extra_terms or [])
    for it in items:
        if it.kind in FIXED_CODES and decisions.get(it.id) == "keep":
            decisions[it.id] = KINDS[it.kind].default_action
    edits, masked = plan_edits(items, decisions)
    out = _output_path(path, Path(output_dir).expanduser().resolve() if output_dir else None)
    say(f"{path.name}: {len(masked)}곳을 가립니다.")
    if path.suffix.lower() == ".pdf":
        report = doc.write(edits, out, manual_boxes=manual_boxes)
    else:
        report = doc.write(edits, out)
    # 만든 사본을 다시 열어 검사한다.
    kept = [it for it in items if it not in masked]
    check = verify_output(out, masked, kept)
    say("다시 검사: " + ("이상 없음" if check["ok"] else "확인 필요"))
    return {
        "output": str(out),
        "masked_count": len(masked),
        "report": report,
        "verify": check,
        "warnings": _warnings(doc),
    }


def verify_output(out: Path, masked, kept) -> dict[str, Any]:
    again = _open(out)
    try:
        units, tables = list(again.units), list(again.tables)
        if out.suffix.lower() == ".hwpx":
            from dpm_hwpx import metadata_text
            from dpm_items import Unit
            meta = metadata_text(out)
            units.append(Unit(uid="meta", text=meta, positions=[None] * len(meta), where="문서 정보·미리보기"))
        return leftover_check(masked, kept, units, tables)
    finally:
        if hasattr(again, "close"):
            again.close()
