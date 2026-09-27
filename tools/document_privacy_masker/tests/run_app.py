"""앱 화면이 부르는 입구(app_analyze · app_page · app_apply)를 점검한다.

    python tests/run_app.py

화면이 보내는 payload 모양 그대로 불러, 사람이 확인한 목록과 결정이 사본에 그대로
반영되는지, 확인하지 않은 상태로는 사본이 만들어지지 않는지 본다.
fixtures 의 파일은 모두 가짜 인물·번호다.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import document_privacy_masker_service as svc  # noqa: E402

FIX = HERE / "fixtures"
failures: list[str] = []


def check(cond: bool, message: str) -> None:
    print(("  ✔ " if cond else "  ✗ ") + message)
    if not cond:
        failures.append(message)


def entry(info: dict, **extra) -> dict:
    """화면이 보내는 파일 하나 몫: 확인한 목록과 기본 결정."""
    out = {
        "path": info["file"],
        "fingerprint": info["fingerprint"],
        "reviewed_ids": [it["id"] for it in info["items"]],
        "decisions": {it["id"]: it["action"] for it in info["items"]},
        "extra_terms": [],
        "manual_boxes": [],
    }
    out.update(extra)
    return out


def hwpx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        return "\n".join(z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.endswith((".xml", ".hpf", ".txt")))


def pdf_text(path: Path) -> str:
    import pymupdf
    with pymupdf.open(path) as doc:
        return re.sub(r"\s+", "", "".join(p.get_text() for p in doc))


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp_text:
        tmp = Path(tmp_text)
        for name in ("hr_notice.hwpx", "hr_form.pdf", "contacts.pdf"):
            shutil.copy(FIX / name, tmp / name)
        hwpx, pdf = tmp / "hr_notice.hwpx", tmp / "hr_form.pdf"

        print("\n[출력] 결과(JSON) 말고는 표준출력에 아무것도 찍지 않음")
        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            svc.app_analyze({"path": str(tmp / "contacts.pdf")})   # 표가 있어 find_tables 를 쓴다
            svc.app_page({"path": str(tmp / "contacts.pdf"), "page": 1})
        check(buf.getvalue() == "", f"표준출력 비어 있음: {buf.getvalue()[:80]!r}")

        print("\n[읽기] app_analyze")
        a = svc.app_analyze({"path": str(hwpx)})
        check(a["ok"] and a["items"] and a["fingerprint"], f"항목 {len(a['items'])}개, 파일 표시 {a['fingerprint']}")
        rrn = next(it for it in a["items"] if it["kind"] == "RRN")
        check("keep" in rrn["previews"] and rrn["fixed"], "법정 7종도 '그대로 둠'을 고를 수 있고 자물쇠 표시가 있음")
        person = next(it for it in a["items"] if it["kind"] == "PERSON")
        check(set(person["previews"]) == {"mask_all", "mask_part", "keep"}, "처리 방식은 전부 가림·일부 가림·가리지 않음 세 가지")
        p = svc.app_analyze({"path": str(pdf)})
        check(len(p["pages"]) == 1 and p["pages"][0]["width"] > 0, "PDF 쪽 크기를 돌려줌")
        check(all(it.get("rects") and it.get("page") for it in p["items"]), "PDF 항목마다 쪽·사각형이 있음")
        check(all(set(it["previews"]) == {"mask_all", "mask_part", "keep"} for it in a["items"] + p["items"]),
              "한글·PDF 모든 항목이 세 가지 방식만")
        phone = next(it for it in p["items"] if it["kind"] == "MOBILE")
        check("■" in phone["previews"]["mask_part"] and phone["previews"]["mask_part"].startswith("010-"),
              f"PDF 는 지워질 자리를 ■ 로 보여 줌: {phone['previews']['mask_part']}")

        print("\n[미리보기] app_page")
        pg = svc.app_page({"path": str(pdf), "page": 1, "width": 600})
        check(pg["image"].startswith("data:image/png;base64,") and pg["page_count"] == 1, "쪽 그림을 돌려줌")
        try:
            svc.app_page({"path": str(pdf), "page": 5})
            check(False, "없는 쪽은 막아야 함")
        except ValueError:
            check(True, "없는 쪽은 알림")

        print("\n[적용] 확인 표시 없이는 만들지 않음")
        try:
            svc.app_apply({"files": [entry(a)]})
            check(False, "확인 없이 만들면 안 됨")
        except ValueError as exc:
            check("확인" in str(exc), f"알림: {exc}")
        check(not list(tmp.glob("*_마스킹*")), "사본이 생기지 않음")

        print("\n[적용] 화면 결정 그대로")
        dec = {it["id"]: it["action"] for it in a["items"]}
        keep_name = next(it for it in a["items"] if it["text"] == "이재민")
        dec[keep_name["id"]] = "keep"
        r = svc.app_apply({"confirmed": True, "files": [entry(a, decisions=dec)]})
        check(r["ok"] and r["popup"]["level"] == "success", f"성공 알림: {r['popup']['title']}")
        body = hwpx_text(Path(r["output"]))
        check("780302-1234564" not in body, "주민번호는 가려짐")
        check("이재민" in body, "'그대로 둠'으로 고른 이름은 남음")
        check("다시 검사" in r["popup"]["message"], "알림에 다시 검사 결과가 있음")

        print("\n[적용] 법정 7종도 사람이 '그대로 둠'을 고르면 남김")
        dec = {it["id"]: it["action"] for it in a["items"]}
        dec[rrn["id"]] = "keep"
        r = svc.app_apply({"confirmed": True, "files": [entry(a, decisions=dec)]})
        body = hwpx_text(Path(r["output"]))
        check("780302-1234564" in body and r["results"][0]["verify"]["ok"], "주민번호가 남고, 사람이 고른 것이라 다시 검사도 통과")

        print("\n[적용] 확인한 뒤 파일이 바뀌면 멈춤")
        info = svc.app_analyze({"path": str(pdf)})
        time.sleep(0.01)
        os.utime(pdf, None)
        r = svc.app_apply({"confirmed": True, "files": [entry(info)]})
        check(not r["results"] and "바뀌었" in r["failed"][0]["error"], f"알림: {r['failed'][0]['error'] if r['failed'] else r}")
        check(r["popup"]["level"] == "error", "실패 알림")

        print("\n[적용] 확인한 목록과 다시 찾은 목록이 다르면 멈춤")
        info = svc.app_analyze({"path": str(pdf)})
        e = entry(info)
        e["reviewed_ids"] = e["reviewed_ids"][1:]
        r = svc.app_apply({"confirmed": True, "files": [e]})
        check(not r["results"] and "다릅니다" in r["failed"][0]["error"], "알림: 목록이 다름")

        print("\n[직접 추가] 이미 찾은 값 안의 글자는 겹쳐 넣지 않음, 새 글자는 항목이 됨")
        base = svc.app_analyze({"path": str(pdf)})
        terms = [{"text": "서준", "kind": "PERSON"}, {"text": "교원인사과", "kind": "CUSTOM"}]
        info = svc.app_analyze({"path": str(pdf), "extra_terms": terms})
        added = [it for it in info["items"] if "직접 추가" in it["reasons"]]
        check(len(info["items"]) == len(base["items"]) + len(added), "원래 항목은 그대로")
        check(all(it["text"] == "교원인사과" for it in added) and added, f"새 글자만 항목이 됨: {[it['text'] for it in added]}")
        r = svc.app_apply({"confirmed": True, "files": [entry(info, extra_terms=terms)]})
        check(r["ok"], "직접 추가한 글자까지 적용")
        check("교원인사과" not in pdf_text(Path(r["output"])), "직접 추가한 글자가 사본에서 사라짐")

        print("\n[직접 그린 영역] PDF 에서 사각형 안 글자를 지움")
        import pymupdf
        with pymupdf.open(pdf) as doc:
            words = [w for w in doc[0].get_text("words") if w[4] in "인사기록카드"]
            hit = pymupdf.Rect(min(w[0] for w in words), min(w[1] for w in words),
                               max(w[2] for w in words), max(w[3] for w in words))
        info = svc.app_analyze({"path": str(pdf)})
        box = {"page": 1, "x0": hit.x0, "y0": hit.y0, "x1": hit.x1, "y1": hit.y1}
        r = svc.app_apply({"confirmed": True, "files": [entry(info, manual_boxes=[box])]})
        check(r["ok"] and not any(ch in pdf_text(Path(r["output"]))[:12] for ch in "록카드"), "그린 영역의 글자가 사라짐")

        print("\n[겹침] 직접 추가가 찾은 값에 걸쳐도 글자가 되살아나지 않음")
        info = svc.app_analyze({"path": str(hwpx), "extra_terms": [{"text": "김민수 외", "kind": "CUSTOM"}]})
        e = entry(info, extra_terms=[{"text": "김민수 외", "kind": "CUSTOM"}])
        check(any(it["text"] == "김민수 외" for it in info["items"]), "걸치는 직접 추가는 따로 항목이 됨")
        r = svc.app_apply({"confirmed": True, "files": [e]})
        body = hwpx_text(Path(r["output"]))
        check(r["ok"] and "김민수" not in body and "*** * 2인" in body, "이름과 '외'가 모두 가려짐")

        print("\n[옛 한글 hwp] 한글로 hwpx 임시 사본을 만들어 읽고, 사본은 hwpx 로 저장")
        import dpm_hancom
        real_convert = dpm_hancom.convert_to_hwpx
        calls = []

        def fake_convert(src, dst):   # 이 시험 PC 에는 한글이 없어 변환 결과를 fixture 로 대신한다
            calls.append(src)
            shutil.copy(FIX / "hr_notice.hwpx", dst)

        dpm_hancom.convert_to_hwpx = fake_convert
        try:
            old = tmp / "인사발령.hwp"
            old.write_bytes(b"\xd0\xcf\x11\xe0" + b"\0" * 512)   # 옛 한글(OLE) 머리
            info = svc.app_analyze({"path": str(old)})
            check(info["format"] == "hwpx" and info["items"] and info["view"], f"hwpx 처럼 읽음: {len(info['items'])}곳")
            check(any("hwp" in w for w in info["warnings"]), "바꿔 읽었다고 알림")
            cache = dpm_hancom.cached_hwpx(old)
            check(cache.exists(), "임시 hwpx 가 있음(찾기와 사본 만들기가 같은 파일을 씀)")
            r = svc.app_apply({"confirmed": True, "files": [entry(info)]})
            check(r["ok"] and Path(r["output"]).name == "인사발령_마스킹.hwpx", f"사본: {Path(r['output']).name}")
            check(len(calls) == 1, f"한글 변환은 한 번만: {len(calls)}번")
            check(not cache.exists(), "사본을 만든 뒤 임시 hwpx 를 지움")
            check("780302-1234564" not in hwpx_text(Path(r["output"])), "사본에서 가려짐")
        finally:
            dpm_hancom.convert_to_hwpx = real_convert
        try:
            svc.app_analyze({"path": str(tmp / "인사발령.hwp")})
            check(False, "한글이 없으면 알려야 함")
        except Exception as exc:
            check("한글" in str(exc), f"한글이 없는 PC: {exc}")

        print("\n[여러 파일] 한 파일이 실패해도 나머지는 만듦")
        good = svc.app_analyze({"path": str(tmp / "contacts.pdf")})
        bad = {"path": str(tmp / "없는파일.pdf")}
        r = svc.app_apply({"confirmed": True, "files": [bad, entry(good)]})
        check(len(r["results"]) == 1 and len(r["failed"]) == 1 and r["popup"]["level"] == "warning",
              f"1개 성공·1개 실패: {r['popup']['title']}")

        print("\n[저장 폴더]")
        out_dir = tmp / "결과"
        info = svc.app_analyze({"path": str(pdf)})
        r = svc.app_apply({"confirmed": True, "output": str(out_dir), "files": [entry(info)]})
        check(Path(r["output"]).parent == out_dir.resolve(), f"고른 폴더에 저장: {Path(r['output']).name}")

    print("\n결과:", "통과" if not failures else f"실패 {len(failures)}건")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
