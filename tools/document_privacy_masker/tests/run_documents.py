"""hwpx·PDF 파일로 '찾기 → 가린 사본 만들기 → 다시 검사'를 끝까지 점검한다.

    python tests/run_documents.py

tests/fixtures 의 파일은 모두 가짜 인물·번호로 만든 것이다.
결과 사본은 임시 폴더에 만들고 지운다(원본 fixtures 는 바뀌지 않아야 한다).
"""
from __future__ import annotations

import hashlib
import re
import shutil
import sys
import tempfile
import xml.dom.minidom
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


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hwpx_all_text(path: Path) -> str:
    out = []
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if name.endswith((".xml", ".hpf", ".txt")):
                out.append(z.read(name).decode("utf-8", "replace"))
    return "\n".join(out)


def pdf_text(path: Path) -> str:
    import pymupdf
    with pymupdf.open(path) as doc:
        return "\n".join(page.get_text() for page in doc)


def flat(s: str) -> str:
    return re.sub(r"\s+", "", s)


def test_hwpx(tmp: Path) -> None:
    print("\n[한글] 인사발령 통보서 (hr_notice.hwpx)")
    src = tmp / "hr_notice.hwpx"
    shutil.copy(FIX / "hr_notice.hwpx", src)
    before = sha(src)
    a = svc.analyze_file(src)
    texts = {it["text"] for it in a["items"]}
    for value in ("김철수(金哲洙)", "780302-1234564", "010-1234-5678", "302-1234-5678-91", "홍길동", "이재민", "익산시 인북로 32"):
        check(value in texts, f"찾음: {value}")
    check("행정지원과" not in "".join(texts), "부서명·문서번호는 찾지 않음")

    dec = {}
    for it in a["items"]:
        if it["text"] == "이재민":
            dec[it["id"]] = "keep"
    r = svc.apply_file(src, dec, extra_terms=[{"text": "박영수", "kind": "PERSON"}])
    out = Path(r["output"])
    check(sha(src) == before, "원본 파일은 바뀌지 않음")
    check(out.name == "hr_notice_마스킹.hwpx", f"사본 이름: {out.name}")
    check(r["verify"]["ok"], f"다시 검사 통과 {r['verify']}")
    with zipfile.ZipFile(out) as z:
        infos = z.infolist()
        check(infos[0].filename == "mimetype" and infos[0].compress_type == zipfile.ZIP_STORED, "mimetype 이 맨 앞·무압축")
        with zipfile.ZipFile(src) as zs:
            check([i.filename for i in infos] == zs.namelist(), "ZIP 안 파일 목록·순서가 원본과 같음")
        for name in z.namelist():
            if name.endswith((".xml", ".hpf")):
                try:
                    xml.dom.minidom.parseString(z.read(name))
                except Exception as exc:  # pragma: no cover
                    check(False, f"XML 깨짐: {name} {exc}")
    body = hwpx_all_text(out)
    for gone in ("김철수", "金哲洙", "780302-1234564", "1234-5678", "302-1234-5678-91", "기린대로", "박영수", "이영희", "김민수",
                 "synthetic-fixture-author"):
        check(gone not in body, f"사본 어디에도 없음(본문·미리보기·문서정보): {gone}")
    for kept in ("인사발령 통보서", "행정지원과-12345", "주무관", "이재민", "010-****-5678", "김*수(***)"):
        check(kept in body, f"사본에 남아 있음: {kept}")

    print("\n[한글] 한 값이 글자 모양 두 덩어리로 나뉜 문서 (split_runs.hwpx)")
    src2 = tmp / "split_runs.hwpx"
    shutil.copy(FIX / "split_runs.hwpx", src2)
    r2 = svc.apply_file(src2)
    body2 = hwpx_all_text(Path(r2["output"]))
    check("7803" not in body2 and "1234564" not in body2, "나뉜 주민번호도 모두 가림")
    check("010-**</hp:t>" in body2 and "**-5678" in body2, "나뉜 휴대전화 가운데만 가림")
    check("&amp; 비고 &lt;없음&gt;" in body2 and "<hp:tab/>" in body2, "특수문자·탭 표시는 그대로")

    print("\n[한글] 확장자만 hwpx 인 옛 hwp")
    try:
        svc.analyze_file(FIX / "fake_ole.hwpx")
        check(False, "옛 hwp 를 알아채야 함")
    except Exception as exc:
        check("옛 한글" in str(exc), f"알림: {exc}")


def test_pdf(tmp: Path) -> None:
    import pymupdf
    print("\n[PDF] 인사기록카드 (hr_form.pdf)")
    src = tmp / "hr_form.pdf"
    shutil.copy(FIX / "hr_form.pdf", src)
    before = sha(src)
    a = svc.analyze_file(src)
    texts = {it["text"] for it in a["items"]}
    for value in ("박서준", "881224-1234566", "010-7777-8888", "psj@naver.com", "123456-01-234567", "한지민", "박하은", "정민규"):
        check(value in texts, f"찾음: {value}")
    r = svc.apply_file(src)
    out = Path(r["output"])
    check(sha(src) == before, "원본 파일은 바뀌지 않음")
    check(r["verify"]["ok"], f"다시 검사 통과 {r['verify']}")
    text = flat(pdf_text(out))
    for gone in ("박서준", "881224", "1234566", "7777", "psj@", "123456-01", "한지민", "박하은", "정민규", "대학로"):
        check(flat(gone) not in text, f"사본 글자에서 사라짐(복사해도 안 나옴): {gone}")
    for kept in ("인사기록카드", "주민등록번호", "교원인사과-4521", "주무관", "010-", "-8888", "@naver.com"):
        check(flat(kept) in text, f"사본에 남아 있음: {kept}")
    with pymupdf.open(out) as doc:
        check(not (doc.metadata.get("author") or doc.metadata.get("creator")), "문서 정보(작성자 등) 비움")

    print("\n[PDF] 표 선·그림이 있는 비상연락망 (contacts.pdf)")
    src2 = tmp / "contacts.pdf"
    shutil.copy(FIX / "contacts.pdf", src2)
    a2 = svc.analyze_file(src2)
    names = {it["text"] for it in a2["items"] if it["kind"] == "PERSON"}
    check({"홍길동", "이남은", "선우진"} <= names, f"'성명' 열로 이름 찾음(값만 봐선 모르는 '이남은' 포함): {sorted(names)}")
    check(any("2쪽" in w for w in a2["warnings"]), "글자 없는 쪽(스캔) 알림")
    r2 = svc.apply_file(src2)
    with pymupdf.open(src2) as d0, pymupdf.open(r2["output"]) as d1:
        lines0 = [d["rect"] for d in d0[0].get_drawings() if not d.get("fill")]
        lines1 = [d["rect"] for d in d1[0].get_drawings() if not d.get("fill")]
        boxes = [d for d in d1[0].get_drawings() if d.get("fill") == (0.0, 0.0, 0.0)]
        check(lines0 == lines1, f"표 선은 그대로({len(lines0)}개)")
        check(len(boxes) >= 1, f"가린 자리에 검은 칸({len(boxes)}개)")
        check(len(d0[0].get_images()) == len(d1[0].get_images()), "그림은 그대로")
        t1 = flat(d1[0].get_text())
    check("홍길동" not in t1 and "이남은" not in t1 and "2222" in t1 and "1111" not in t1, "이름·번호 가운데만 사라짐")

    print("\n[PDF] 처리할 수 없는 파일")
    for name, word in (("encrypted.pdf", "암호"), ("scanned.pdf", "스캔")):
        try:
            svc.analyze_file(FIX / name)
            check(False, f"{name} 를 막아야 함")
        except Exception as exc:
            check(word in str(exc), f"{name}: {exc}")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        test_hwpx(Path(tmp))
        test_pdf(Path(tmp))
    print("\n결과:", "통과" if not failures else f"실패 {len(failures)}건")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
