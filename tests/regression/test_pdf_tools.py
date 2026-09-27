"""PDF 도구 회귀 점검.

    python tests/regression/test_pdf_tools.py

앱과 같은 방식(bridge/runner.py --tool ... --payload-b64 ...)으로 도구를 불러 결과를 본다.
입력 PDF·이미지는 실행할 때 임시 폴더에 만든다. Word·PowerPoint·한글(COM)은 여기서
돌릴 수 없으므로 가짜 COM 객체를 끼워 처리부(service)만 점검한다.
"""
from __future__ import annotations

import base64
import importlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import traceback
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
RUNNER = ROOT / "bridge" / "runner.py"
PROGRESS = "@@JBEDU_PROGRESS@@"

import pymupdf  # noqa: E402
from PIL import Image  # noqa: E402

failures: list[str] = []


def check(cond: bool, message: str) -> None:
    print(("  ✔ " if cond else "  ✗ ") + message)
    if not cond:
        failures.append(message)


# ----------------------------------------------------------------- 실행 도우미

class Run:
    def __init__(self, code: int, stdout: str, stderr: str):
        self.code = code
        self.stdout = stdout
        self.stderr = stderr
        self.body_lines = [
            line for line in stdout.splitlines() if not line.strip().startswith(PROGRESS)
        ]
        self.progress = [
            line.strip()[len(PROGRESS):] for line in stdout.splitlines()
            if line.strip().startswith(PROGRESS)
        ]
        try:
            self.result = json.loads("\n".join(self.body_lines).strip())
        except Exception:
            self.result = None

    @property
    def clean_stdout(self) -> bool:
        """앱(lib.rs)처럼 진행 줄을 빼고 남은 것이 JSON 하나인지."""
        return self.code == 0 and isinstance(self.result, dict)


def run_tool(tool: str, payload: dict, env: dict | None = None) -> Run:
    data = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("ascii")
    full_env = dict(os.environ)
    full_env["JBEDU_TOOLS_ROOT"] = str(TOOLS)
    full_env["PYTHONIOENCODING"] = "utf-8"
    full_env.pop("JBEDU_CANCEL_FILE", None)
    if env:
        full_env.update(env)
    proc = subprocess.run(
        [sys.executable, str(RUNNER), "--tool", tool, "--payload-b64", data],
        capture_output=True,
        env=full_env,
        timeout=300,
    )
    return Run(
        proc.returncode,
        proc.stdout.decode("utf-8", "replace"),
        proc.stderr.decode("utf-8", "replace"),
    )


def load_service(tool_id: str, module: str):
    folder = str(TOOLS / tool_id)
    if folder not in sys.path:
        sys.path.insert(0, folder)
    return importlib.import_module(module)


# ----------------------------------------------------------------- 입력 만들기

_CJK = None


def cjk_font() -> bytes:
    global _CJK
    if _CJK is None:
        _CJK = pymupdf.Font("cjk").buffer
    return _CJK


def text_pdf(path: Path, pages: list[list[str]]) -> Path:
    doc = pymupdf.open()
    for lines in pages:
        page = doc.new_page()
        page.insert_font(fontname="kr", fontbuffer=cjk_font())
        y = 100
        for line in lines:
            page.insert_text((72, y), line, fontname="kr", fontsize=12)
            y += 22
    doc.save(str(path))
    doc.close()
    return path


def certificate_lines(name: str, number: str, course: str = "학교폭력 예방 연수") -> list[str]:
    return [
        "이 수 증",
        f"연수번호: {number}",
        "근무기관: 전북초등학교",
        "직급: 교사",
        f"성명: {name}",
        f"과정명: {course}",
        "연수기간: 2026.03.01 ~ 2026.03.31",
        "전북교연",
    ]


def blank_pdf(path: Path, count: int = 3, size=(595, 842)) -> Path:
    doc = pymupdf.open()
    for _ in range(count):
        doc.new_page(width=size[0], height=size[1])
    doc.save(str(path))
    doc.close()
    return path


def rotated_pdf(path: Path) -> Path:
    """0/90/180/270 회전 페이지와 원점이 (100,200)인 MediaBox 페이지."""
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import RectangleObject

    tmp = path.with_name(path.stem + "_src.pdf")
    doc = pymupdf.open()
    for rotation in (0, 90, 180, 270):
        page = doc.new_page(width=595, height=842)
        page.set_rotation(rotation)
    doc.new_page(width=612, height=792)
    doc.save(str(tmp))
    doc.close()
    reader = PdfReader(str(tmp))
    writer = PdfWriter()
    for index, page in enumerate(reader.pages):
        if index == 4:
            page.mediabox = RectangleObject([100, 200, 712, 992])
            page.cropbox = RectangleObject([100, 200, 712, 992])
        writer.add_page(page)
    with open(path, "wb") as handle:
        writer.write(handle)
    return path


def encrypted_pdf(src: Path, path: Path) -> Path:
    doc = pymupdf.open(str(src))
    doc.save(str(path), encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="u1", owner_pw="o1")
    doc.close()
    return path


def broken_xref_pdf(path: Path) -> Path:
    """pypdf 는 못 읽고(startxref 없음) MuPDF 는 복구해서 여는 PDF."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "repair me")
    data = doc.tobytes()
    doc.close()
    path.write_bytes(data.replace(b"startxref", b"startxrXf"))
    return path


def bad_stream_pdf(path: Path, with_image: bool = False) -> Path:
    """내용 스트림이 조금 깨진 PDF. MuPDF 가 'MuPDF error: ...' 를 찍는다."""
    doc = pymupdf.open()
    page = doc.new_page()
    if with_image:
        page.insert_image(pymupdf.Rect(50, 50, 550, 550), stream=noise_png(600))
    page.insert_text((72, 72), "hello")
    xrefs = page.get_contents()
    body = b"".join(doc.xref_stream(x) for x in xrefs)
    doc.update_stream(
        xrefs[0],
        body + b" q 1 0 0 1 0 0 cm /Im99 Do Q ) ] >> garbage BI ID xx EI 5 0 obj",
    )
    for extra in xrefs[1:]:
        doc.update_stream(extra, b"")
    doc.save(str(path))
    doc.close()
    return path


def noise_png(size: int) -> bytes:
    image = Image.frombytes("RGB", (size, size), os.urandom(size * size * 3))
    buf = io.BytesIO()
    image.save(buf, "PNG")
    return buf.getvalue()


def photo_pdf(path: Path, pages: int = 1) -> Path:
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page()
        page.insert_image(page.rect, stream=noise_png(900))
    doc.save(str(path))
    doc.close()
    return path


def displayed_lines(page) -> list[dict]:
    """페이지에 적힌 글줄을 '화면에 보이는' 좌표와 방향으로."""
    rot = page.rotation_matrix
    turn = pymupdf.Matrix(rot.a, rot.b, rot.c, rot.d, 0, 0)
    lines = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = "".join(span["text"] for span in line["spans"]).strip()
            if not text:
                continue
            direction = pymupdf.Point(*line["dir"]) * turn
            lines.append({
                "text": text,
                "rect": pymupdf.Rect(line["bbox"]) * rot,
                "dir": (round(direction.x, 3), round(direction.y, 3)),
            })
    return lines


def excel_rows(path: Path) -> dict:
    import pandas as pd

    return {name: frame.fillna("").to_dict("records") for name, frame in pd.read_excel(path, sheet_name=None).items()}


# ----------------------------------------------------------------- 점검

def test_page_number_ui_values(tmp: Path) -> None:
    print("[1] 페이지 번호: 화면이 보내는 형식·위치 값")
    src = blank_pdf(tmp / "pn_src.pdf", 3)
    cases = [
        ("숫자 / 전체", "상단 오른쪽", "1 / 3", "top", "right"),
        ("- 숫자 -", "하단 왼쪽", "- 1 -", "bottom", "left"),
        ("숫자", "상단 가운데", "1", "top", "center"),
    ]
    for index, (fmt, pos, expected, vertical, horizontal) in enumerate(cases):
        out = tmp / f"pn_ui_{index}.pdf"
        run = run_tool("pdf_page_number_adder", {
            "inputs": [str(src)], "output": str(out),
            "format_type": fmt, "position": pos, "start_page": 1, "start_number": 1, "font_size": 10,
        })
        ok = False
        detail = run.stderr.strip()[:120]
        if run.clean_stdout and out.exists():
            with pymupdf.open(str(out)) as doc:
                page = doc[0]
                lines = displayed_lines(page)
                detail = str([(l["text"], tuple(round(v) for v in l["rect"])) for l in lines])
                w, h = page.rect.width, page.rect.height
                for line in lines:
                    r = line["rect"]
                    cx = (r.x0 + r.x1) / 2
                    v_ok = r.y1 < h * 0.15 if vertical == "top" else r.y0 > h * 0.85
                    h_ok = {"left": r.x1 < w * 0.3, "right": r.x0 > w * 0.7,
                            "center": abs(cx - w / 2) < w * 0.05}[horizontal]
                    if line["text"] == expected and v_ok and h_ok:
                        ok = True
        check(ok, f"형식 '{fmt}' · 위치 '{pos}' → '{expected}' 가 {vertical}-{horizontal} 에 찍힘 {'' if ok else detail}")

    service = load_service("pdf_page_number_adder", "pdf_page_number_adder_service")
    out = tmp / "pn_legacy.pdf"
    try:
        service.add_page_numbers(src, out, "1 / 전체페이지수", 1, 1, "우하단", "굴림체", 10)
        with pymupdf.open(str(out)) as doc:
            lines = displayed_lines(doc[0])
            w, h = doc[0].rect.width, doc[0].rect.height
        ok = any(l["text"] == "1 / 3" and l["rect"].x0 > w * 0.7 and l["rect"].y0 > h * 0.85 for l in lines)
    except Exception as error:
        ok = False
        print("     ", error)
    check(ok, "예전 값('1 / 전체페이지수', '우하단')도 그대로 동작")


def test_page_number_rotation(tmp: Path) -> None:
    print("[2] 페이지 번호: 회전·원점이 다른 페이지에서 보이는 모양대로")
    src = rotated_pdf(tmp / "pn_rot.pdf")
    out = tmp / "pn_rot_out.pdf"
    run = run_tool("pdf_page_number_adder", {
        "inputs": [str(src)], "output": str(out), "format_type": "숫자", "position": "하단 가운데",
    })
    if not (run.clean_stdout and out.exists()):
        check(False, f"실행 실패: {run.stderr.strip()[:200]}")
        return
    labels = ["회전 0", "회전 90", "회전 180", "회전 270", "MediaBox 원점 (100,200)"]
    with pymupdf.open(str(out)) as doc:
        for index, page in enumerate(doc):
            w, h = page.rect.width, page.rect.height
            lines = [l for l in displayed_lines(page) if l["text"] == str(index + 1)]
            ok = False
            detail = "번호 없음(페이지 밖)"
            for line in lines:
                r = line["rect"]
                cx = (r.x0 + r.x1) / 2
                upright = line["dir"] == (1.0, 0.0)
                placed = abs(cx - w / 2) < w * 0.05 and r.y0 > h * 0.85 and r.y1 <= h + 0.5
                detail = f"위치 {tuple(round(v) for v in r)} / 방향 {line['dir']} / 쪽 {round(w)}x{round(h)}"
                ok = ok or (upright and placed)
            check(ok, f"{labels[index]}: 번호가 똑바로 하단 가운데에 보임 {'' if ok else detail}")


def test_combiner_same_stem(tmp: Path) -> None:
    print("[3] PDF 통합: 이름이 같은 입력이 서로 덮어쓰지 않음")
    (tmp / "a").mkdir()
    (tmp / "b").mkdir()
    Image.new("RGB", (60, 60), (255, 0, 0)).save(tmp / "a" / "scan.png")
    Image.new("RGB", (60, 60), (0, 0, 255)).save(tmp / "b" / "scan.png")
    out = tmp / "same_stem.pdf"
    run = run_tool("multi_format_pdf_combiner", {
        "inputs": [str(tmp / "a" / "scan.png"), str(tmp / "b" / "scan.png")], "output": str(out),
    })
    colors = []
    if run.clean_stdout and out.exists():
        with pymupdf.open(str(out)) as doc:
            for page in doc:
                pix = page.get_pixmap(matrix=pymupdf.Matrix(0.2, 0.2))
                colors.append(pix.pixel(pix.width // 2, pix.height // 2))
    ok = len(colors) == 2 and colors[0][0] > 200 and colors[0][2] < 60 and colors[1][2] > 200 and colors[1][0] < 60
    check(ok, f"a/scan.png(빨강) + b/scan.png(파랑) → 빨강·파랑 두 쪽 (실제: {colors})")

    service = load_service("multi_format_pdf_combiner", "multi_format_pdf_combiner_service")
    work = tmp / "stem_work"
    work.mkdir()
    (work / "보고서.hwp").write_bytes(b"hwp")
    (work / "보고서.docx").write_bytes(b"docx")
    saved = {}
    try:
        orig_word, orig_hwp = service.convert_with_word, service.convert_with_hancom

        def fake_word(src, out, *args, **kwargs):
            text_pdf(Path(out), [["WORD"]])
            return True, "OK"

        def fake_hwp(src, out, *args, **kwargs):
            text_pdf(Path(out), [["HANCOM"]])
            return True, "OK"

        service.convert_with_word, service.convert_with_hancom = fake_word, fake_hwp
        try:
            conv = tmp / "conv"
            conv.mkdir()
            p1, _ = service.ensure_pdf(work / "보고서.hwp", conv)
            p2, _ = service.ensure_pdf(work / "보고서.docx", conv)
            for key, path in (("hwp", p1), ("docx", p2)):
                with pymupdf.open(str(path)) as doc:
                    saved[key] = doc[0].get_text().strip()
        finally:
            service.convert_with_word, service.convert_with_hancom = orig_word, orig_hwp
    except Exception as error:
        saved["error"] = str(error)
    check(saved.get("hwp") == "HANCOM" and saved.get("docx") == "WORD",
          f"보고서.hwp + 보고서.docx 변환본이 각각 남음 ({saved})")


class _Recorder:
    def __init__(self):
        self.calls: list = []


def fake_win32com(recorder: _Recorder, register_ok: str | None = None, ppt_open: int = 0):
    """Word·PowerPoint·한글 COM 을 흉내 내는 가짜 win32com 과 pythoncom."""

    class Doc:
        def ExportAsFixedFormat(self, OutputFileName, ExportFormat):
            recorder.calls.append(("word.export", ExportFormat))
            text_pdf(Path(OutputFileName), [["WORD"]])

        def Close(self, *args):
            recorder.calls.append(("word.close",))

    class Documents:
        Count = 0

        def Open(self, path, *args, **kwargs):
            recorder.calls.append(("word.open", str(path)))
            return Doc()

    class Word:
        def __init__(self):
            self.Documents = Documents()
            self.DisplayAlerts = -1
            self._visible = True

        @property
        def Visible(self):
            return self._visible

        @Visible.setter
        def Visible(self, value):
            recorder.calls.append(("word.visible", bool(value)))
            self._visible = value

        def Quit(self):
            recorder.calls.append(("word.quit",))

    class Pres:
        def SaveAs(self, path, fmt):
            recorder.calls.append(("ppt.saveas", fmt))
            text_pdf(Path(path), [["PPT"]])

        def Close(self):
            pass

    class Presentations:
        Count = ppt_open  # 사용자가 이미 열어 둔 프레젠테이션 수

        def Open(self, path, *args, **kwargs):
            recorder.calls.append(("ppt.open", str(path)))
            return Pres()

    class PowerPoint:
        def __init__(self):
            self.Presentations = Presentations()
            self.Visible = 0

        def Quit(self):
            recorder.calls.append(("ppt.quit",))

    class Window:
        def __init__(self):
            self._visible = None

        @property
        def Visible(self):
            return self._visible

        @Visible.setter
        def Visible(self, value):
            recorder.calls.append(("hwp.visible", bool(value)))
            self._visible = value

    class Windows:
        def __init__(self):
            self.window = Window()

        def Item(self, index):
            return self.window

    class ParamSet:
        def __init__(self):
            self.HSet = object()
            self.filename = ""
            self.Format = ""

    class HAction:
        def __init__(self, owner):
            self.owner = owner

        def GetDefault(self, name, hset):
            pass

        def Execute(self, name, hset):
            ps = self.owner.HParameterSet.HFileOpenSave
            recorder.calls.append(("hwp.saveas", ps.Format))
            text_pdf(Path(ps.filename), [["HANCOM"]])
            return True

    class Hwp:
        def __init__(self):
            self.XHwpWindows = Windows()
            self.HParameterSet = types.SimpleNamespace(HFileOpenSave=ParamSet())
            self.HAction = HAction(self)

        def RegisterModule(self, kind, name):
            recorder.calls.append(("hwp.register", name))
            return name == register_ok

        def Open(self, path, *args):
            recorder.calls.append(("hwp.open", str(path)))
            return True

        def Clear(self, *args):
            pass

        def Quit(self):
            recorder.calls.append(("hwp.quit",))

    def dispatch(name, *args, **kwargs):
        recorder.calls.append(("Dispatch", name))
        if "HWPFrame" in name:
            # 예전 방식(gen_py 캐시를 쓰는 Dispatch)으로 불러도 한글은 만들어 준다.
            return Hwp()
        raise AssertionError(f"Dispatch 로 {name} 에 붙음(사용자 창을 건드릴 수 있음)")

    def dispatch_ex(name, *args, **kwargs):
        recorder.calls.append(("DispatchEx", name))
        return {"Word.Application": Word, "PowerPoint.Application": PowerPoint}[name]()

    def dynamic_dispatch(name, *args, **kwargs):
        recorder.calls.append(("dynamic.Dispatch", name))
        return Hwp()

    client = types.SimpleNamespace(
        Dispatch=dispatch, DispatchEx=dispatch_ex,
        dynamic=types.SimpleNamespace(Dispatch=dynamic_dispatch),
    )
    win32com = types.SimpleNamespace(client=client)
    pythoncom = types.SimpleNamespace(CoInitialize=lambda: None, CoUninitialize=lambda: None)
    return win32com, pythoncom


def with_fake_com(service, recorder, register_ok=None, ppt_open=0):
    win32com, pythoncom = fake_win32com(recorder, register_ok, ppt_open)
    saved = (service.PYWIN32_AVAILABLE, getattr(service, "win32com", None), getattr(service, "pythoncom", None))
    service.PYWIN32_AVAILABLE = True
    service.win32com = win32com
    service.pythoncom = pythoncom
    return saved


def restore_com(service, saved) -> None:
    service.PYWIN32_AVAILABLE, service.win32com, service.pythoncom = saved


def test_combiner_doc_and_images(tmp: Path) -> None:
    print("[4] PDF 통합: .doc 받기, 이미지 회전(EXIF)·여러 쪽 TIFF·16비트")
    service = load_service("multi_format_pdf_combiner", "multi_format_pdf_combiner_service")
    work = tmp / "doc_work"
    work.mkdir()
    (work / "옛문서.doc").write_bytes(b"old word")
    recorder = _Recorder()
    saved = with_fake_com(service, recorder)
    try:
        conv = tmp / "doc_conv"
        conv.mkdir()
        pdf, error = service.ensure_pdf(work / "옛문서.doc", conv)
    except Exception as exc:
        pdf, error = None, str(exc)
    finally:
        restore_com(service, saved)
    opened = [c[1] for c in recorder.calls if c[0] == "word.open"]
    check(pdf is not None and Path(pdf).exists(), f".doc 를 Word 로 PDF 변환 (오류: {error})")
    check(bool(opened) and opened[0].lower().endswith(".doc"),
          f"Word 에 .doc 확장자 그대로 넘김 (연 파일: {opened})")

    # 이미지: 러너로 실제 실행
    exif_jpg = work / "세로사진.jpg"
    image = Image.new("RGB", (80, 40), (0, 128, 0))
    exif = Image.Exif()
    exif[0x0112] = 6  # 시계 방향 90도 돌려 보라는 표시 → 보이는 모양은 세로(40x80)
    image.save(exif_jpg, "JPEG", exif=exif.tobytes())
    tiff = work / "여러쪽.tif"
    frames = [Image.new("RGB", (50, 70), color) for color in ((255, 0, 0), (0, 255, 0), (0, 0, 255))]
    frames[0].save(tiff, save_all=True, append_images=frames[1:])
    gray16 = work / "16비트.png"
    Image.frombytes("I;16", (64, 32), bytes(range(256)) * 16).save(gray16)
    out = tmp / "images.pdf"
    run = run_tool("multi_format_pdf_combiner", {
        "inputs": [str(exif_jpg), str(tiff), str(gray16)], "output": str(out),
    })
    sizes = []
    if run.clean_stdout and out.exists():
        with pymupdf.open(str(out)) as doc:
            sizes = [(round(p.rect.width), round(p.rect.height)) for p in doc]
    failed = (run.result or {}).get("failed") if run.result else run.stderr.strip()[:200]
    check(len(sizes) >= 1 and sizes[0][0] < sizes[0][1], f"EXIF 회전 반영: 세로 사진이 세로 쪽으로 (쪽 크기: {sizes[:1]})")
    check(len(sizes) == 5, f"여러 쪽 TIFF 3쪽 + 사진 1 + 16비트 PNG 1 = 5쪽 (실제 {len(sizes)}쪽, 실패: {failed})")
    check(run.result is not None and not (run.result or {}).get("failed"), f"16비트 PNG 도 실패 없이 처리 (실패: {failed})")


def test_combiner_repair(tmp: Path) -> None:
    print("[5] PDF 통합: 손상 PDF 복구를 설치본에 있는 PyMuPDF 로")
    source = (TOOLS / "multi_format_pdf_combiner" / "multi_format_pdf_combiner_service.py").read_text(encoding="utf-8")
    check("import pikepdf" not in source, "pikepdf(설치본에 없음)에 기대지 않음")
    good = text_pdf(tmp / "good.pdf", [["GOOD"]])
    broken = broken_xref_pdf(tmp / "broken.pdf")
    out = tmp / "repaired_out.pdf"
    run = run_tool("multi_format_pdf_combiner", {"inputs": [str(good), str(broken)], "output": str(out)})
    pages = 0
    if run.clean_stdout and out.exists():
        with pymupdf.open(str(out)) as doc:
            pages = doc.page_count
    failed = (run.result or {}).get("failed") if run.result else run.stderr.strip()[:200]
    check(pages == 2 and not failed, f"startxref 가 깨진 PDF 도 복구해 합침 ({pages}쪽, 실패: {failed})")
    check(not (tmp / "_tmp_pdf_repair").exists(), "저장 폴더에 복구용 임시 폴더를 남기지 않음")


def test_combiner_com_isolation(tmp: Path) -> None:
    print("[6] PDF 통합: Office 는 새 인스턴스로, 한글은 늦은 바인딩·보안 모듈·허용 안내")
    service = load_service("multi_format_pdf_combiner", "multi_format_pdf_combiner_service")
    work = tmp / "com_work"
    work.mkdir()
    for name in ("a.docx", "b.pptx", "c.hwp", "d.hwp"):
        (work / name).write_bytes(b"x")

    recorder = _Recorder()
    saved = with_fake_com(service, recorder)
    try:
        ok_word, msg_word = service.convert_with_word(work / "a.docx", tmp / "a_out.pdf")
        ok_ppt, msg_ppt = service.convert_with_powerpoint(work / "b.pptx", tmp / "b_out.pdf")
    finally:
        restore_com(service, saved)
    check(ok_word and ("DispatchEx", "Word.Application") in recorder.calls,
          f"Word 는 DispatchEx 로 새로 띄움 ({msg_word})")
    check(ok_ppt and ("DispatchEx", "PowerPoint.Application") in recorder.calls,
          f"PowerPoint 는 DispatchEx 로 띄움 ({msg_ppt})")
    check(not any(c[0] == "Dispatch" for c in recorder.calls), "사용자 Office 에 붙는 Dispatch 를 쓰지 않음")

    # PowerPoint 는 하나만 떠서 사용자의 창에 붙을 수 있다: 열린 발표 자료가 있으면 끄지 않는다.
    recorder = _Recorder()
    saved = with_fake_com(service, recorder, ppt_open=1)
    try:
        ok_ppt, msg_ppt = service.convert_with_powerpoint(work / "b.pptx", tmp / "b_out2.pdf")
    finally:
        restore_com(service, saved)
    check(ok_ppt and ("ppt.quit",) not in recorder.calls,
          f"사용자가 PowerPoint 를 쓰는 중이면 Quit() 하지 않음 ({msg_ppt})")

    # 보안 모듈이 하나도 등록되지 않으면: 한글 창을 보이게 하고 '허용' 안내
    recorder = _Recorder()
    notes: list[str] = []
    os.environ["HWP_FILE_PATH_CHECKER_MODULE"] = "MyCheckerModule"
    saved = with_fake_com(service, recorder, register_ok=None)
    try:
        try:
            ok_hwp, msg_hwp = service.convert_with_hancom(work / "c.hwp", tmp / "c_out.pdf", notes.append)
        except TypeError as error:  # 진행 안내를 받을 자리가 없음
            ok_hwp, msg_hwp = service.convert_with_hancom(work / "c.hwp", tmp / "c_out.pdf")
            msg_hwp = f"{msg_hwp} / {error}"
    finally:
        restore_com(service, saved)
        os.environ.pop("HWP_FILE_PATH_CHECKER_MODULE", None)
    tried = [c[1] for c in recorder.calls if c[0] == "hwp.register"]
    visible = [c[1] for c in recorder.calls if c[0] == "hwp.visible"]
    check(ok_hwp, f"한글 변환 성공 ({msg_hwp})")
    check(("dynamic.Dispatch", "HWPFrame.HwpObject") in recorder.calls,
          "한글은 늦은 바인딩(win32com.client.dynamic.Dispatch)으로 띄움")
    check(tried == ["MyCheckerModule", "SecurityModule", "FilePathCheckerModule", "FilePathCheckerModuleExample"],
          f"보안 모듈을 환경변수 → SecurityModule → FilePathCheckerModule → …Example 순으로 시도 ({tried})")
    check(bool(visible) and visible[-1] is True, f"등록 실패 시 한글 창을 보이게 둠 ({visible})")
    check(any("허용" in note for note in notes), f"'허용'을 누르라는 진행 안내 ({notes})")

    # 등록에 성공하면 창은 숨긴다.
    recorder = _Recorder()
    saved = with_fake_com(service, recorder, register_ok="FilePathCheckerModule")
    try:
        try:
            ok_hwp, _ = service.convert_with_hancom(work / "d.hwp", tmp / "d_out.pdf", None)
        except TypeError:
            ok_hwp, _ = service.convert_with_hancom(work / "d.hwp", tmp / "d_out.pdf")
    finally:
        restore_com(service, saved)
    visible = [c[1] for c in recorder.calls if c[0] == "hwp.visible"]
    check(ok_hwp and visible and visible[-1] is False,
          f"FilePathCheckerModule 등록에 성공하면 창을 숨김 ({visible})")


def test_combiner_failed_contract(tmp: Path) -> None:
    print("[7] PDF 통합: 실패한 파일을 failed 로 알리고 메시지가 전부 성공이라 하지 않음")
    good = text_pdf(tmp / "ok1.pdf", [["OK"]])
    bad = tmp / "깨진파일.pdf"
    bad.write_bytes(b"this is not a pdf at all")
    out = tmp / "contract.pdf"
    run = run_tool("multi_format_pdf_combiner", {"inputs": [str(good), str(bad)], "output": str(out)})
    result = run.result or {}
    failed = result.get("failed")
    shape_ok = (
        isinstance(failed, list) and len(failed) == 1 and isinstance(failed[0], dict)
        and failed[0].get("name") == "깨진파일.pdf" and re.search(r"[가-힣]", str(failed[0].get("error", "")))
    )
    check(bool(shape_ok), f"failed: [{{name, error}}] 형태 (실제: {failed})")
    message = str(result.get("message", ""))
    check("2개 중 1개" in message and "1개는 처리하지 못했습니다" in message, f"메시지에 실패가 드러남 ({message})")


def test_mupdf_stdout(tmp: Path) -> None:
    print("[8] MuPDF 오류 문구가 stdout(결과 JSON)에 섞이지 않음")
    bad = bad_stream_pdf(tmp / "badstream.pdf")
    run = run_tool("pdf_page_organizer__load", {"inputs": [str(bad)]})
    check(run.clean_stdout and "MuPDF" not in run.stdout,
          f"페이지 정리 불러오기 (stdout 앞부분: {run.stdout[:80]!r})")
    run = run_tool("pdf_page_organizer__preview", {"inputs": [str(bad)], "page": 0})
    check(run.clean_stdout and "MuPDF" not in run.stdout, f"페이지 정리 크게 보기 ({run.stdout[:80]!r})")
    run = run_tool("pdf_page_organizer", {
        "sequence": [{"path": str(bad), "page": 0, "rotate": 90}], "output": str(tmp / "seq_out"),
    })
    check(run.clean_stdout and "MuPDF" not in run.stdout, f"페이지 정리 저장 ({run.stdout[:80]!r})")
    bad_img = bad_stream_pdf(tmp / "badstream_img.pdf", with_image=True)
    run = run_tool("pdf_compress", {"inputs": [str(bad_img)], "target_mb": 0.05, "output": str(tmp / "cmp_bad")})
    check(run.clean_stdout and "MuPDF" not in run.stdout, f"PDF 압축 ({run.stdout[:80]!r})")


def test_renamer_inputs(tmp: Path) -> None:
    print("[9] 이수증 파일명 변경: 바뀐 경로를 돌려줘 이어서 다시 돌릴 수 있음")
    folder = tmp / "rename"
    folder.mkdir()
    src = text_pdf(folder / "스캔001.pdf", [certificate_lines("홍길동", "제2026-001호")])
    payload = {"inputs": [str(src)], "confirmed": True, "filename_fields": "성명,근무기관", "delimiter": "_"}
    run = run_tool("certificate_pdf_renamer", payload)
    inputs = (run.result or {}).get("inputs")
    ok = isinstance(inputs, list) and len(inputs) == 1 and Path(inputs[0]).exists() and Path(inputs[0]).name == "홍길동_전북초등학교.pdf"
    check(ok, f"result.inputs 에 새 경로 ({inputs}; {run.stderr.strip()[:120]})")
    again = run_tool("certificate_pdf_renamer", dict(payload, inputs=inputs or payload["inputs"]))
    check(again.code == 0, f"돌려받은 목록으로 한 번 더 실행해도 성공 ({again.stderr.strip()[:120]})")


def test_collector_multi(tmp: Path) -> None:
    print("[10] 이수증 취합: 여러 이수증이 묶인 PDF, 암호 PDF")
    folder = tmp / "collect"
    folder.mkdir()
    bundle = text_pdf(folder / "묶음.pdf", [
        certificate_lines("홍길동", "제2026-001호"),
        certificate_lines("김철수", "제2026-002호"),
        certificate_lines("이영희", "제2026-003호"),
    ])
    two_page = text_pdf(folder / "두쪽.pdf", [
        certificate_lines("박민수", "제2026-010호"),
        ["붙임: 연수 세부 일정", "1일차 개회", "2일차 강의"],
    ])
    locked = encrypted_pdf(text_pdf(folder / "원본.pdf", [certificate_lines("최지우", "제2026-020호")]), folder / "암호.pdf")
    out = folder / "result.xlsx"
    run = run_tool("certificate_pdf_collector", {"inputs": [str(bundle), str(two_page), str(locked)], "output": str(out)})
    sheets = excel_rows(out) if out.exists() else {}
    rows = sheets.get("정상", []) + sheets.get("확인필요", [])
    names = sorted(str(r.get("성명", "")) for r in rows)
    check(names == sorted(["홍길동", "김철수", "이영희", "박민수"]),
          f"묶음 PDF 3명 + 두 쪽짜리 1명 = 4행 (실제: {names}; {run.stderr.strip()[:120]})")
    errors = sheets.get("에러", [])
    message = str(errors[0].get("에러메시지", "")) if errors else ""
    check(bool(errors) and "암호" in message, f"암호 PDF 는 한국어 사유 ({message!r})")


def test_compress_cancel(tmp: Path) -> None:
    print("[11] PDF 압축: 중지했을 때")
    folder = tmp / "compress"
    folder.mkdir()
    a = photo_pdf(folder / "사진1.pdf")
    b = photo_pdf(folder / "사진2.pdf")
    flag = folder / "cancel.flag"
    flag.write_text("1")
    env = {"JBEDU_CANCEL_FILE": str(flag)}

    run = run_tool("pdf_compress", {
        "inputs": [str(a), str(b)], "target_mb": 0.05, "target_mode": "each", "output": str(folder / "each"),
    }, env)
    popup = (run.result or {}).get("popup") or {}
    check(run.code == 0 and popup.get("level") != "success" and "중지" in str(popup),
          f"파일마다: 첫 파일 전에 중지하면 성공 팝업이 뜨지 않음 (팝업: {popup.get('level')} {popup.get('title')})")

    run = run_tool("pdf_compress", {
        "inputs": [str(a), str(b)], "target_mb": 0.05, "target_mode": "total", "output": str(folder / "total"),
    }, env)
    outputs = (run.result or {}).get("outputs") or []
    popup = (run.result or {}).get("popup") or {}
    check(run.code == 0 and len(outputs) == 2 and all(Path(o["path"]).exists() for o in outputs),
          f"전체 합계: 중지해도 결과를 버리지 않고 저장 ({run.stderr.strip()[:120]})")
    check(popup.get("level") == "warning" and "중지" in str(popup), f"전체 합계: 중지했다고 알림 ({popup.get('title')})")

    flag.unlink()
    run = run_tool("pdf_compress", {
        "inputs": [str(a)], "target_mb": 0.05, "target_mode": "each", "output": str(folder / "normal"),
    })
    check(run.code == 0 and len((run.result or {}).get("outputs") or []) == 1, "중지하지 않으면 평소처럼 압축")


ENGLISH = ("decrypted", "Failed to open", "EOF marker", "invalid literal", "Stream has ended", "startxref")


def korean_error(run: Run, name: str, word: str) -> tuple[bool, str]:
    text = run.stderr.strip()
    ok = run.code != 0 and name in text and word in text and not any(e in text for e in ENGLISH)
    return ok, text[:160]


def test_english_errors(tmp: Path) -> None:
    print("[12] 영어 오류 대신 파일 이름을 담은 한국어 안내")
    folder = tmp / "errors"
    folder.mkdir()
    locked = encrypted_pdf(blank_pdf(folder / "plain.pdf", 2), folder / "잠긴문서.pdf")
    junk = folder / "깨진문서.pdf"
    junk.write_bytes(b"not a pdf, just text" * 10)
    truncated = folder / "잘린문서.pdf"
    data = (folder / "plain.pdf").read_bytes()
    truncated.write_bytes(data[: data.rfind(b"%%EOF")].replace(b"startxref", b"startxrXf"))

    run = run_tool("pdf_page_number_adder", {"inputs": [str(locked)], "output": str(folder / "o1.pdf")})
    ok, text = korean_error(run, "잠긴문서.pdf", "암호")
    check(ok, f"페이지 번호 · 암호 PDF ({text!r})")

    run = run_tool("pdf_page_number_adder", {"inputs": [str(truncated)], "output": str(folder / "o2.pdf")})
    ok, text = korean_error(run, "잘린문서.pdf", "손상")
    check(ok, f"페이지 번호 · 깨진 PDF ({text!r})")

    run = run_tool("pdf_page_number_adder", {
        "inputs": [str(folder / "plain.pdf")], "output": str(folder / "o3.pdf"), "start_page": "1.5쪽",
    })
    text = run.stderr.strip()
    check(run.code != 0 and "숫자" in text and "invalid literal" not in text, f"페이지 번호 · 숫자 아닌 입력 ({text[:120]!r})")

    run = run_tool("pdf_page_organizer", {
        "inputs": [str(junk)], "action": "extract", "mode": "pages", "spec": "1", "output": str(folder / "o4"),
    })
    ok, text = korean_error(run, "깨진문서.pdf", "손상")
    check(ok, f"페이지 정리 · PDF 아님 ({text!r})")

    run = run_tool("pdf_page_organizer", {
        "inputs": [str(locked)], "action": "split", "mode": "every_n", "number": "두", "output": str(folder / "o5"),
    })
    text = run.stderr.strip()
    check(run.code != 0 and "숫자" in text and "invalid literal" not in text, f"페이지 정리 · 숫자 아닌 입력 ({text[:120]!r})")

    run = run_tool("pdf_page_organizer__load", {"inputs": [str(junk)]})
    ok, text = korean_error(run, "깨진문서.pdf", "손상")
    check(ok, f"페이지 미리보기 편집 불러오기 · PDF 아님 ({text!r})")

    run = run_tool("pdf_compress", {"inputs": [str(junk), str(locked)], "target_mb": 0.0001, "output": str(folder / "o6")})
    text = run.stderr.strip()
    ok = run.code != 0 and "깨진문서.pdf" in text and "손상" in text and "암호" in text and not any(e in text for e in ENGLISH)
    check(ok, f"PDF 압축 · 깨진/암호 PDF ({text[:160]!r})")

    good = text_pdf(folder / "정상.pdf", [["OK"]])
    run = run_tool("multi_format_pdf_combiner", {"inputs": [str(good), str(locked)], "output": str(folder / "o7.pdf")})
    failed = (run.result or {}).get("failed") or []
    reason = str(failed[0].get("error", "")) if failed and isinstance(failed[0], dict) else str(failed)
    check("암호" in reason and not any(e in reason for e in ENGLISH), f"PDF 통합 · 암호 PDF ({reason!r})")

    rename_dir = folder / "rename"
    rename_dir.mkdir()
    locked_cert = encrypted_pdf(text_pdf(folder / "cert.pdf", [certificate_lines("홍길동", "제1호")]), rename_dir / "잠긴이수증.pdf")
    run = run_tool("certificate_pdf_renamer", {"inputs": [str(locked_cert)], "confirmed": True})
    failed = (run.result or {}).get("failed") or []
    reason = str(failed[0].get("error", "")) if failed else ""
    check("암호" in reason, f"이수증 파일명 변경 · 암호 PDF ({reason!r})")

    split_dir = folder / "split"
    run = run_tool("certificate_pdf_splitter", {"inputs": [str(locked_cert)], "output": str(split_dir)})
    failed = (run.result or {}).get("failed") or []
    reason = str(failed[0].get("error", "")) if failed else ""
    check("암호" in reason and not any(e in reason for e in ENGLISH), f"이수증 분리 · 암호 PDF ({reason!r})")


TESTS = [
    test_page_number_ui_values,
    test_page_number_rotation,
    test_combiner_same_stem,
    test_combiner_doc_and_images,
    test_combiner_repair,
    test_combiner_com_isolation,
    test_combiner_failed_contract,
    test_mupdf_stdout,
    test_renamer_inputs,
    test_collector_multi,
    test_compress_cancel,
    test_english_errors,
]


def main() -> int:
    only = set(sys.argv[1:])
    with tempfile.TemporaryDirectory(prefix="jbedu_pdf_regress_") as name:
        base = Path(name)
        for test in TESTS:
            if only and not any(key in test.__name__ for key in only):
                continue
            folder = base / test.__name__
            folder.mkdir()
            try:
                test(folder)
            except Exception:
                check(False, f"{test.__name__} 실행 중 예외\n{traceback.format_exc()}")
    print()
    if failures:
        print(f"✗ 실패 {len(failures)}건")
        return 1
    print("✔ 모두 통과")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
