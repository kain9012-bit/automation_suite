"""문서 개인정보 마스킹 — 앱(사이드카)이 부르는 입구.

두 단계로 쓴다.
  1) analyze_file(path)            : 문서를 읽어 찾은 개인정보 목록을 돌려준다(파일은 만들지 않음).
  2) apply_file(path, decisions…)  : 사람이 확인한 결정대로 가린 사본을 만들고, 사본을 다시 열어 검사한다.

분석과 적용 사이에 문서를 다시 읽어 같은 규칙으로 찾기 때문에 항목 id 가 그대로 맞는다.
원본 파일은 절대 고치지 않는다. 사본 이름: '원본이름_마스킹.hwpx' / '원본이름_마스킹.pdf'
(옛 한글 hwp 는 한글로 hwpx 로 바꿔 읽고 사본도 hwpx 로 저장한다. dpm_hancom 참고)
(같은 이름이 있으면 '(1)' 을 붙인다).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Optional

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from dpm_items import combine_terms, find_items, items_for_terms, leftover_check, plan_edits  # noqa: E402
from dpm_kinds import ACTION_LABELS, KINDS, MASK_ALL  # noqa: E402
from dpm_mask import masked_text  # noqa: E402
# 한글·PDF 모듈도 여기서 불러 둔다. 설치본을 만들 때 사이드카 자체 점검(--selftest)이
# 이 파일을 불러 보므로, 빠진 라이브러리가 있으면 배포 전에 드러난다.
import dpm_hancom  # noqa: E402,F401
import dpm_hwpx  # noqa: E402,F401
import dpm_pdf  # noqa: E402,F401

SUPPORTED = (".hwp", ".hwpx", ".pdf")


def _work_path(path: Path) -> Path:
    """실제로 읽을 파일. 옛 한글(hwp) 형식이면 한글로 바꾼 임시 hwpx(확장자가 hwpx 인데 속이 hwp 인 것도)."""
    if path.suffix.lower() in (".hwp", ".hwpx"):
        from dpm_hancom import working_hwpx
        return working_hwpx(path)
    return path


def _open(path: Path):
    """path 는 _work_path 를 거친 파일."""
    ext = path.suffix.lower()
    if ext in (".hwpx", ".hwp"):
        from dpm_hwpx import HwpxDoc, check_hwpx
        check_hwpx(path)
        return HwpxDoc(path)
    if ext == ".pdf":
        from dpm_pdf import PdfDoc
        return PdfDoc(path)
    raise ValueError(f"지원하지 않는 형식입니다: {path.suffix} (hwp, hwpx, pdf 만 됩니다)")


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


def fingerprint(path: Path) -> str:
    """확인한 뒤 적용하기 전에 파일이 바뀌었는지 알아보는 표시(크기·수정 시각)."""
    st = path.stat()
    return f"{st.st_size}:{st.st_mtime_ns}"


def _collect(doc, extra_terms: Optional[list[dict]]):
    items = find_items(doc.units, doc.tables)
    return combine_terms(items, items_for_terms(doc.units, doc.tables, extra_terms or []))


def _previews(kind: str, text: str, is_pdf: bool) -> dict[str, str]:
    """처리 방식마다 바뀐 모양. PDF 는 지운 글자 자리가 검은 칸이 되므로 ■ 로 보여 준다."""
    out = {}
    for action in ACTION_LABELS:
        new = masked_text(kind, text, action)
        if is_pdf and new != text:
            if len(new) == len(text):
                new = "".join("■" if a != b else a for a, b in zip(text, new))
            else:
                new = "".join(ch if ch in " \n" else "■" for ch in text)
        out[action] = new
    return out


def _changes(kind: str, text: str) -> dict[str, list[int]]:
    """처리 방식마다 바뀌는 글자 자리(찾은 글 안의 순번). 미리보기에서 원래 글자 위에 칠할 곳."""
    out = {}
    for action in ACTION_LABELS:
        new = masked_text(kind, text, action)
        if new == text:
            out[action] = []
        elif len(new) == len(text):
            out[action] = [i for i, (a, b) in enumerate(zip(text, new)) if a != b]
        else:
            out[action] = [i for i, ch in enumerate(text) if not ch.isspace()]
    return out


def analyze_file(path: str | Path, extra_terms: Optional[list[dict]] = None) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    stamp = fingerprint(path)
    work = _work_path(path)
    doc = _open(work)
    try:
        if not doc.units:
            if getattr(doc, "scanned_pages", None):
                raise ValueError("글자가 없는 PDF(스캔본)입니다. 이 도구는 스캔 문서를 처리하지 않습니다.")
            raise ValueError("문서에서 글자를 찾지 못했습니다.")
        items = _collect(doc, extra_terms)
        is_pdf = hasattr(doc, "char_rect")
        dicts = [it.to_dict() for it in items]
        for it, d in zip(items, dicts):
            d["previews"] = _previews(it.kind, it.text, is_pdf)
            d["changes"] = _changes(it.kind, it.text)
        pages = []
        view = []
        hwp_preview = None
        if is_pdf:
            # PDF: 미리보기에서 칠해 보여 줄 자리(쪽 번호와 사각형)
            from dpm_pdf import _merge_rects
            for it, d in zip(items, dicts):
                rects = [doc.char_rect[k] for k in it.keys if k in doc.char_rect]
                d["page"] = it.keys[0][0] + 1 if it.keys else None
                d["rects"] = [[round(v, 1) for v in r] for r in _merge_rects(rects)]
                # 글자마다 사각형(찾은 글과 같은 순서, 줄바꿈 등은 None): 바뀌는 글자만 칠하는 데 쓴다.
                d["char_rects"] = [
                    [round(v, 1) for v in doc.char_rect[p]] if p is not None and p in doc.char_rect else None
                    for p in it.positions
                ]
            pages = [{"width": round(p.rect.width, 1), "height": round(p.rect.height, 1)} for p in doc.doc]
        elif hasattr(doc, "view"):
            # 한글: 문단·표를 글로 다시 그린 미리보기와, 찾은 글자마다 그 안의 자리
            view, spot = doc.view()
            paras, para_spot = doc.paragraphs()
            for it, d in zip(items, dicts):
                d["spots"] = [spot.get(p) if p is not None else None for p in it.positions]
                d["pspots"] = [para_spot.get(p) if p is not None else None for p in it.positions]
            # 쪽 미리보기: 화면이 한글 문서를 직접 쪽 그림으로 그린다(rhwp). 그리는 파일과 문단 글을 함께 넘긴다.
            if work.stat().st_size <= 40 * 1024 * 1024:
                import base64
                hwp_preview = {"data": base64.b64encode(work.read_bytes()).decode("ascii"), "paras": paras}
        return {
            "file": str(path),
            "name": path.name,
            "format": "pdf" if is_pdf else "hwpx",
            "fingerprint": stamp,
            "items": dicts,
            "counts": _counts(items),
            "warnings": (["옛 한글(hwp) 형식이라 한글로 hwpx 로 바꿔 읽었습니다. 가린 사본은 hwpx 로 저장합니다."]
                         if work != path else []) + _warnings(doc),
            "pages": pages,
            "view": view,
            "hwp_preview": hwp_preview,
            "scanned_pages": list(getattr(doc, "scanned_pages", [])),
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


def _output_path(path: Path, output_dir: Optional[Path], suffix: Optional[str] = None) -> Path:
    folder = output_dir or path.parent
    folder.mkdir(parents=True, exist_ok=True)
    ext = suffix or path.suffix.lower()
    base = folder / f"{path.stem}_마스킹{ext}"
    if not base.exists():
        return base
    n = 1
    while (folder / f"{path.stem}_마스킹({n}){ext}").exists():
        n += 1
    return folder / f"{path.stem}_마스킹({n}){ext}"


def apply_file(
    path: str | Path,
    decisions: Optional[dict[str, str]] = None,
    extra_terms: Optional[list[dict]] = None,
    manual_boxes: Optional[list[dict]] = None,
    output_dir: Optional[str | Path] = None,
    log: Optional[Callable[[str], None]] = None,
    expected_fingerprint: Optional[str] = None,
    reviewed_ids: Optional[list[str]] = None,
) -> dict[str, Any]:
    """decisions: {항목 id: 처리 방식}. 적지 않은 항목은 기본 처리 방식을 쓴다.
    사람이 '가리지 않음'을 고른 항목은 종류와 상관없이 그대로 둔다.

    expected_fingerprint·reviewed_ids 를 주면(앱 화면), 확인한 뒤 파일이 바뀌었거나 다시 찾은
    항목이 화면에서 확인한 목록과 다르면 사본을 만들지 않고 멈춘다. 사람이 보지 않은 항목이
    처리되는 일을 막기 위해서다."""
    say = log or (lambda _t: None)
    path = Path(path).expanduser().resolve()
    decisions = dict(decisions or {})
    if expected_fingerprint and fingerprint(path) != expected_fingerprint:
        raise ValueError(f"{path.name}: 확인한 뒤 파일이 바뀌었습니다. 파일을 다시 읽어 확인해 주세요.")
    work = _work_path(path)
    doc = _open(work)
    items = _collect(doc, extra_terms)
    if reviewed_ids is not None and {it.id for it in items} != set(reviewed_ids):
        if hasattr(doc, "close"):
            doc.close()
        raise ValueError(f"{path.name}: 화면에서 확인한 목록과 다시 찾은 목록이 다릅니다. 파일을 다시 읽어 확인해 주세요.")
    is_pdf = work.suffix.lower() == ".pdf"
    for it in items:
        if decisions.get(it.id) not in (None, *ACTION_LABELS):
            decisions[it.id] = MASK_ALL   # 세 가지 방식 밖의 값은 전부 가림으로
    edits, masked = plan_edits(items, decisions)
    out = _output_path(path, Path(output_dir).expanduser().resolve() if output_dir else None,
                       suffix=".pdf" if is_pdf else ".hwpx")
    say(f"{path.name}: {len(masked)}곳을 가립니다.")
    if is_pdf:
        report = doc.write(edits, out, manual_boxes=manual_boxes)
    else:
        report = doc.write(edits, out)
    # 만든 사본을 다시 열어 검사한다.
    kept = [it for it in items if it not in masked]
    check = verify_output(out, masked, kept)
    if work != path:
        from dpm_hancom import forget
        forget(path)   # 개인정보가 든 임시 hwpx 는 사본을 만든 뒤 지운다
    say("다시 검사: " + ("이상 없음" if check["ok"] else "확인 필요"))
    return {
        "output": str(out),
        "masked_count": len(masked),
        "manual_boxes": len(manual_boxes or []) if is_pdf else 0,
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


# ---------------------------------------------------------------- 앱 화면에서 부르는 입구
# bridge/extra_tools.py 는 아래 세 함수에 payload 를 그대로 넘기기만 한다.
# 화면과 주고받는 모양을 이 도구 폴더 안에서만 정해, 공용 파일 수정을 한 줄씩으로 줄인다.

def _one_path(value: Any) -> Path:
    text = str(value or "").strip()
    if not text:
        raise ValueError("처리할 파일을 선택하세요.")
    path = Path(text).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {path}")
    return path


def _terms(value: Any) -> list[dict]:
    out = []
    for term in value or []:
        if isinstance(term, dict) and str(term.get("text") or "").strip():
            out.append({"text": str(term["text"]).strip(), "kind": str(term.get("kind") or "CUSTOM")})
    return out


def app_analyze(payload: dict[str, Any], progress: Optional[Callable[[str], None]] = None) -> dict[str, Any]:
    """파일 하나를 읽어 찾은 항목을 돌려준다. 파일은 만들지 않는다."""
    path = _one_path(payload.get("path"))
    if progress:
        progress(f"{path.name} 읽는 중")
    info = analyze_file(path, extra_terms=_terms(payload.get("extra_terms")))
    return {"ok": True, "message": f"{path.name}: {len(info['items'])}곳을 찾았습니다.", **info}


def app_page(payload: dict[str, Any]) -> dict[str, Any]:
    """PDF 한 쪽을 그림으로 돌려준다(확인 화면 미리보기). 좌표는 PDF 단위(pt)."""
    import base64
    import pymupdf

    path = _one_path(payload.get("path"))
    page_no = int(payload.get("page") or 1)
    width = max(300, min(int(payload.get("width") or 900), 1800))
    with pymupdf.open(path) as doc:
        if not 1 <= page_no <= doc.page_count:
            raise ValueError(f"{page_no}쪽이 없습니다.")
        page = doc[page_no - 1]
        zoom = width / max(page.rect.width, 1)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        data = base64.b64encode(pix.tobytes("png")).decode("ascii")
        return {
            "ok": True,
            "message": "",
            "image": f"data:image/png;base64,{data}",
            "page": page_no,
            "page_count": doc.page_count,
            "width": round(page.rect.width, 1),
            "height": round(page.rect.height, 1),
        }


def app_apply(
    payload: dict[str, Any],
    progress: Optional[Callable[[str], None]] = None,
    cancel: Optional[Callable[[], bool]] = None,
) -> dict[str, Any]:
    """화면에서 확인한 결정대로 파일마다 가린 사본을 만든다.

    payload = {
      files: [{path, fingerprint, reviewed_ids, decisions, extra_terms, manual_boxes}],
      output: 저장 폴더(비우면 원본과 같은 폴더),
      confirmed: 사람이 확인했다는 표시(없으면 만들지 않는다)
    }"""
    say = progress or (lambda _t: None)
    if not payload.get("confirmed"):
        raise ValueError("찾은 항목을 확인했다고 표시한 뒤 실행하세요.")
    files = [f for f in payload.get("files") or [] if isinstance(f, dict)]
    if not files:
        raise ValueError("처리할 파일을 선택하세요.")
    output_text = str(payload.get("output") or "").strip()
    output_dir = Path(output_text).expanduser().resolve() if output_text else None

    results, failed, stopped = [], [], False
    for index, entry in enumerate(files, start=1):
        if cancel and cancel():
            stopped = True
            break
        name = Path(str(entry.get("path") or "")).name or f"{index}번째 파일"
        say(f"[{index}/{len(files)}] {name}")
        try:
            path = _one_path(entry.get("path"))
            decisions = {str(k): str(v) for k, v in (entry.get("decisions") or {}).items()}
            reviewed = entry.get("reviewed_ids")
            result = apply_file(
                path,
                decisions,
                extra_terms=_terms(entry.get("extra_terms")),
                manual_boxes=[b for b in entry.get("manual_boxes") or [] if isinstance(b, dict)],
                output_dir=output_dir,
                log=say,
                expected_fingerprint=str(entry.get("fingerprint") or "") or None,
                reviewed_ids=[str(i) for i in reviewed] if isinstance(reviewed, list) else None,
            )
            result["name"] = path.name
            results.append(result)
        except Exception as exc:  # 한 파일이 실패해도 나머지는 계속한다.
            failed.append({"name": name, "error": str(exc)})
            say(f"{name}: 만들지 못했습니다 ({exc})")

    popup = _popup(results, failed, stopped, len(files))
    first = results[0]["output"] if results else ""
    return {
        "ok": bool(results) and not failed,
        "message": popup["title"],
        "output": first,
        "results": results,
        "failed": failed,
        "stopped": stopped,
        "popup": popup,
    }


def _popup(results: list[dict], failed: list[dict], stopped: bool, total: int) -> dict[str, str]:
    lines: list[str] = []
    problem = bool(failed) or stopped
    for r in results:
        verify = r.get("verify") or {}
        lines.append(f"{r['name']} → {Path(r['output']).name} ({r['masked_count']}곳 가림)")
        if verify.get("ok"):
            lines.append("  ✔ 다시 검사: 가린 값이 사본에 남아 있지 않습니다.")
        else:
            problem = True
            for left in (verify.get("remained") or [])[:8]:
                lines.append(f"  ⚠ 사본에 같은 글자가 남아 있음: {left['label']} '{left['text']}' "
                             f"(가린 곳: {left['where']}). 다른 자리에도 쓰였는지 확인하세요.")
            for left in (verify.get("fixed_left") or [])[:8]:
                lines.append(f"  ⚠ 가려지지 않은 {left['label']}: '{left['text']}'")
        report = r.get("report") or {}
        extra = []
        if r.get("manual_boxes"):
            extra.append(f"직접 그린 영역 {r['manual_boxes']}개 지움")
        if report.get("metadata_cleared"):
            extra.append("문서 정보(작성자 등) 비움")
        if report.get("annotations_removed"):
            extra.append(f"메모 {report['annotations_removed']}개 뺌")
        if report.get("attachments_removed"):
            extra.append(f"첨부 파일 {report['attachments_removed']}개 뺌")
        if report.get("toc_titles_masked"):
            extra.append(f"책갈피 제목 {report['toc_titles_masked']}개 가림")
        if report.get("preview_text") or report.get("preview_image"):
            extra.append("한글 미리보기 새로 만듦")
        if extra:
            lines.append("  · " + ", ".join(extra))
        for w in (r.get("warnings") or [])[:3]:
            lines.append(f"  · {w}")
    for f in failed:
        lines.append(f"✗ {f['name']}: {f['error']}")
    if stopped:
        lines.append(f"중지했습니다. {total}개 중 {len(results) + len(failed)}개까지 처리했습니다.")
    lines.append("")
    lines.append("원본 파일은 바뀌지 않았습니다. 사본을 열어 한 번 더 눈으로 확인한 뒤 쓰세요.")
    if not results:
        return {"level": "error", "title": "가린 사본을 만들지 못했습니다", "message": "\n".join(lines)}
    return {
        "level": "warning" if problem else "success",
        "title": "가린 사본을 만들었지만 확인이 필요합니다" if problem else f"가린 사본 {len(results)}개를 만들었습니다",
        "message": "\n".join(lines),
    }
