"""한글(HWP) COM 도구 회귀 확인 — 한글 없이 가짜 COM 객체로 돌린다.

대상: tools/hwp_collector, tools/hwp_to_pdf_converter, tools/hwp_to_hwpx_converter 와
bridge/runner.py 의 run_hwp_collector / run_hwp_to_pdf / run_hwp_to_hwpx.

실행: python tests/regression/test_hwp_tools.py   (실패가 하나라도 있으면 종료 코드 1)
"""
from __future__ import annotations

import contextlib
import importlib
import io
import json
import os
import sys
import tempfile
import traceback
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROGRESS = "@@JBEDU_PROGRESS@@"
HINT = "한글이 파일 접근을 물으면 [허용]을 눌러 주세요."


# ------------------------------------------------------------------ 가짜 COM
class State:
    def reset(self) -> None:
        self.hwps: list[FakeHwp] = []
        self.dispatch_calls = 0
        # True: gen_py 캐시가 망가진 PC(win32com.client.Dispatch 가 실패).
        # 기본은 False 로 두어, 다른 결함 확인이 이 결함에 가려지지 않게 한다.
        self.dispatch_broken = False
        self.ensure_calls = 0
        self.dynamic_calls: list[str] = []
        self.progids_ok = {"HWPFrame.HwpObject"}
        self.accepted_modules = {"SecurityModule"}
        self.open_result = True
        self.open_raises = False
        self.path_empty = False
        self.insert_fail: set[str] = set()
        self.open_fail: set[str] = set()
        self.save_raises = False
        self.on_open = None
        self.on_insert = None
        self.coinit = 0
        self.couninit = 0
        # hwp 를 hwpx 로 저장할 때 한글이 적어 넣을 인쇄 방식(None 이면 예전처럼 가짜 바이트만 쓴다).
        self.print_method = None


S = State()
S.reset()


class FakeWindow:
    def __init__(self, hwp):
        self._hwp = hwp

    @property
    def Visible(self):
        return self._hwp.visible[-1] if self._hwp.visible else False

    @Visible.setter
    def Visible(self, value):
        self._hwp.visible.append(bool(value))


class FakeWindows:
    def __init__(self, hwp):
        self._w = FakeWindow(hwp)

    def Item(self, _i):
        return self._w


class FakeParam:
    def __init__(self):
        self.HSet = self
        self.filename = ""
        self.Format = ""
        self.KeepSection = None   # 코드가 직접 정하는지 보려고 비워 둔다
        self.Attributes = 0


class FakeParamSets:
    def __init__(self):
        self.HInsertFile = FakeParam()
        self.HFileOpenSave = FakeParam()


SETTINGS_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?><ha:HWPApplicationSetting '
    'xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app" '
    'xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0">'
    '<ha:CaretPosition listIDRef="0" paraIDRef="0" pos="0"/><config:config-item-set name="PrintInfo">'
    '<config:config-item name="PrintAutoFootNote" type="boolean">false</config:config-item>'
    '<config:config-item name="PrintMethod" type="short">{method}</config:config-item>'
    '<config:config-item name="ZoomX" type="short">100</config:config-item>'
    '</config:config-item-set></ha:HWPApplicationSetting>'
)


def make_hwpx(path, method, source: str = "") -> Path:
    """한글이 저장한 hwpx 와 같은 짜임(mimetype 맨 앞 무압축, settings.xml 의 PrintMethod)."""
    import zipfile
    path = Path(path)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/hwp+zip")
        z.writestr("version.xml", "<version/>", compress_type=zipfile.ZIP_DEFLATED)
        if method is not None:
            z.writestr("settings.xml", SETTINGS_XML.format(method=method), compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("Contents/section0.xml", f"<sec> source {source}</sec>", compress_type=zipfile.ZIP_DEFLATED)
    return path


def print_method_of(path) -> int | None:
    """테스트 쪽에서 직접 읽는 인쇄 방식(도구 코드를 쓰지 않는다)."""
    import re
    import zipfile
    try:
        with zipfile.ZipFile(path) as z:
            data = z.read("settings.xml").decode("utf-8")
    except Exception:
        return None
    m = re.search(r'name="PrintMethod"[^>]*>(\d+)<', data)
    return int(m.group(1)) if m else None


def write_by_format(path: str, fmt: str) -> None:
    fmt = (fmt or "").upper()
    if fmt.startswith("HWPX") and S.print_method is not None:
        make_hwpx(path, S.print_method, "saved")
        return
    if fmt == "PDF":
        data = b"%PDF-1.4 fake"
    elif fmt.startswith("HWPX"):
        data = b"PK\x03\x04 fake hwpx"
    else:  # 형식을 안 주면 한글은 HWP(이진)로 저장한다.
        data = b"\xd0\xcf\x11\xe0 fake hwp"
    Path(path).write_bytes(data)


class FakeAction:
    def __init__(self, hwp):
        self._hwp = hwp

    def Run(self, name):
        self._hwp.actions.append(name)
        return True

    def GetDefault(self, _name, _hset):
        return True

    def Execute(self, name, hset):
        self._hwp.actions.append(name)
        if name == "InsertFile":
            fname = Path(hset.filename).name
            if S.on_insert:
                S.on_insert(fname)
            if fname in S.insert_fail:
                return False
            self._hwp.inserted.append(fname)
            self._hwp.keep_section.append(hset.KeepSection)
            return True
        if name in ("FileSaveAs", "FileSaveAs_S"):
            if S.save_raises:
                raise RuntimeError("save boom")
            write_by_format(hset.filename, hset.Format)
            return True
        return True


class FakeHwp:
    def __init__(self):
        self.visible: list[bool] = []
        self.registered: list[str] = []
        self.actions: list[str] = []
        self.inserted: list[str] = []
        self.opened: list[str] = []
        self.opened_paths: list[str] = []
        self.opened_print: list = []   # 열 때 그 파일에 적혀 있던 인쇄 방식
        self.keep_section: list = []
        self.saved: list[tuple] = []
        self.quit_called = False
        self._path = ""
        self.held = None   # 한글이 열어 둔(쥐고 있는) 파일. 이 파일은 덮어쓸 수 없다.
        self.XHwpWindows = FakeWindows(self)
        self.HAction = FakeAction(self)
        self.HParameterSet = FakeParamSets()

    def RegisterModule(self, _kind, name):
        self.registered.append(name)
        return name in S.accepted_modules

    def Open(self, path, fmt="", opt=""):
        if S.on_open:
            S.on_open(Path(path).name)
        if S.open_raises:
            raise RuntimeError("open boom")
        if not S.open_result:
            return False
        source = _source_name(path)
        if source in S.open_fail:
            return False
        self._path = "" if S.path_empty else path
        self.held = path
        self.opened.append(source)
        self.opened_paths.append(path)
        self.opened_print.append(print_method_of(path))
        return True

    @property
    def Path(self):
        return self._path

    def SaveAs(self, path, fmt=None, arg=None):
        self.saved.append((path, fmt))
        if S.save_raises:
            raise RuntimeError("save boom")
        write_by_format(path, fmt or "")
        if str(fmt or "").upper().startswith("HWPX"):
            # 실제 한글: 다른 이름으로 저장하면 지금 문서가 그 파일이 되고 그 파일을 쥐고 있다.
            self._path = path
            self.held = path
        return True

    def Clear(self, _n):
        self._path = ""
        self.held = None

    def Quit(self):
        self.quit_called = True
        self.held = None


def _source_name(path: str) -> str:
    """가짜 원본 파일에는 원래 이름을 적어 둔다. 임시 복사본을 열어도 어느 파일인지 안다."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return Path(path).name
    marker = b" source "
    return data.split(marker, 1)[1].decode("utf-8") if marker in data else Path(path).name


def _new_hwp():
    hwp = FakeHwp()
    S.hwps.append(hwp)
    return hwp


def _broken_dispatch(*_a, **_k):
    S.dispatch_calls += 1
    if not S.dispatch_broken:
        return _new_hwp()
    raise AttributeError("module 'win32com.gen_py.7D2B6F3C' has no attribute 'CLSIDToPackageMap'")


def _ensure_dispatch(*_a, **_k):
    # 동작은 하지만 gen_py 캐시를 만든다(다른 도구를 망가뜨리는 원인).
    S.ensure_calls += 1
    return _new_hwp()


def _dynamic_dispatch(prog_id, *_a, **_k):
    S.dynamic_calls.append(prog_id)
    if prog_id not in S.progids_ok:
        raise Exception("잘못된 클래스 문자열입니다.")
    return _new_hwp()


def _coinit():
    S.coinit += 1


def _couninit():
    S.couninit += 1


_real_replace = os.replace


def _replace_unless_held(src, dst, *a, **k):
    """한글이 쥐고 있는 파일 위로는 덮어쓸 수 없다(실제 한글에서 '액세스가 거부되었습니다')."""
    target = os.path.normcase(os.path.abspath(dst))
    for hwp in S.hwps:
        if hwp.held and os.path.normcase(os.path.abspath(hwp.held)) == target:
            raise PermissionError(5, "액세스가 거부되었습니다", str(dst))
    return _real_replace(src, dst, *a, **k)


def install_stubs() -> None:
    os.replace = _replace_unless_held
    pythoncom = types.ModuleType("pythoncom")
    pythoncom.CoInitialize = _coinit
    pythoncom.CoUninitialize = _couninit
    win32com = types.ModuleType("win32com")
    client = types.ModuleType("win32com.client")
    dynamic = types.ModuleType("win32com.client.dynamic")
    gencache = types.ModuleType("win32com.client.gencache")
    client.Dispatch = _broken_dispatch
    dynamic.Dispatch = _dynamic_dispatch
    gencache.EnsureDispatch = _ensure_dispatch
    client.dynamic = dynamic
    client.gencache = gencache
    win32com.client = client
    sys.modules.update({
        "pythoncom": pythoncom,
        "win32com": win32com,
        "win32com.client": client,
        "win32com.client.dynamic": dynamic,
        "win32com.client.gencache": gencache,
    })


install_stubs()
for sub in ("hwp_collector", "hwp_to_pdf_converter", "hwp_to_hwpx_converter", "multi_format_pdf_combiner"):
    sys.path.insert(0, str(ROOT / "tools" / sub))
sys.path.insert(0, str(ROOT / "bridge"))
os.environ["JBEDU_PROJECT_ROOT"] = str(ROOT)
os.environ.pop("JBEDU_CANCEL_FILE", None)
os.environ.pop("HWP_FILE_PATH_CHECKER_MODULE", None)

collector = importlib.import_module("hwp_collector_service")
pdfconv = importlib.import_module("hwp_to_pdf_converter_service")
hwpx = importlib.import_module("hwp_to_hwpx_converter_service")
runner = importlib.import_module("runner")
combiner = importlib.import_module("multi_format_pdf_combiner_service")


# ------------------------------------------------------------------ 도우미
def make_files(folder: Path, names: list[str]) -> list[Path]:
    paths = []
    for name in names:
        p = folder / name
        p.write_bytes(b"\xd0\xcf\x11\xe0 source " + name.encode("utf-8"))
        paths.append(p)
    return paths


def run_runner(tool: str, payload: dict, cancel_file: Path | None = None):
    """runner.main 을 실제처럼 돌리고 (반환 코드, 결과 JSON, 진행 줄, stdout 전체) 를 준다."""
    if cancel_file is not None:
        os.environ["JBEDU_CANCEL_FILE"] = str(cancel_file)
    out, err = io.StringIO(), io.StringIO()
    argv = sys.argv
    sys.argv = ["runner", "--tool", tool, "--payload", json.dumps(payload, ensure_ascii=False)]
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = runner.main()
    finally:
        sys.argv = argv
        os.environ.pop("JBEDU_CANCEL_FILE", None)
    lines = [line for line in out.getvalue().splitlines() if line.strip()]
    progress = [line[len(PROGRESS):] for line in lines if line.startswith(PROGRESS)]
    others = [line for line in lines if not line.startswith(PROGRESS)]
    result = None
    if others:
        try:
            result = json.loads(others[-1])
        except Exception:
            result = None
    assert len(others) <= 1, f"stdout 에 JSON/진행 줄 말고 다른 것이 있음: {others}"
    return code, result, progress, err.getvalue()


def all_quit() -> bool:
    return bool(S.hwps) and all(h.quit_called for h in S.hwps)


def balanced() -> bool:
    return S.coinit == S.couninit and S.coinit > 0


RESULTS: list[tuple[str, bool, str]] = []


def check(name):
    def deco(fn):
        S.reset()
        with tempfile.TemporaryDirectory() as tmp:
            try:
                fn(Path(tmp))
                RESULTS.append((name, True, ""))
            except Exception as error:
                detail = f"{type(error).__name__}: {error}"
                if not isinstance(error, AssertionError):
                    detail += "\n" + traceback.format_exc(limit=3)
                RESULTS.append((name, False, detail))
        return fn
    return deco


# ------------------------------------------------------------------ 1. PDF: 늦은 바인딩
@check("1 PDF: gen_py 캐시가 망가져도(Dispatch 실패) dynamic 으로 변환")
def _(tmp):
    S.dispatch_broken = True
    (src,) = make_files(tmp, ["a.hwp"])
    ok, bad = pdfconv.convert_files([src], tmp / "out")
    assert ok == ["a.hwp"] and not bad, f"ok={ok} bad={bad}"
    assert (tmp / "out" / "a.pdf").read_bytes().startswith(b"%PDF")
    assert S.dispatch_calls == 0, "win32com.client.Dispatch 를 불렀음"


@check("1 PDF: 다른 ProgID(HwpFrame.HwpObject)만 등록된 PC 에서도 변환")
def _(tmp):
    S.dispatch_broken = True
    S.progids_ok = {"HwpFrame.HwpObject"}
    (src,) = make_files(tmp, ["a.hwp"])
    ok, bad = pdfconv.convert_files([src], tmp / "out")
    assert ok == ["a.hwp"], f"bad={bad}"


# ------------------------------------------------------------------ 2. HWPX: gencache 안 씀
@check("2 HWPX: gencache.EnsureDispatch/Dispatch 를 쓰지 않고 dynamic 으로 변환(원본 삭제 유지)")
def _(tmp):
    S.dispatch_broken = True
    (src,) = make_files(tmp, ["a.hwp"])
    batch = hwpx.convert_hwp_files_to_hwpx([src])
    assert S.ensure_calls == 0, "gencache.EnsureDispatch 를 불렀음(gen_py 캐시 생성)"
    assert S.dispatch_calls == 0, "win32com.client.Dispatch 를 불렀음"
    assert S.dynamic_calls, "dynamic.Dispatch 를 쓰지 않음"
    assert batch.success_count == 1, batch
    assert (tmp / "a.hwpx").read_bytes().startswith(b"PK")
    assert not src.exists(), "변환된 원본 hwp 는 지워져야 함(의도된 동작)"


@check("2 HWPX: 한글을 띄운 뒤 준비 단계가 실패해도 한글을 끈다")
def _(tmp):
    (src,) = make_files(tmp, ["a.hwp"])
    original = hwpx.try_register_file_path_security_module

    def boom(_hwp):
        raise RuntimeError("register boom")

    hwpx.try_register_file_path_security_module = boom
    try:
        try:
            hwpx.convert_hwp_files_to_hwpx([src])
        except RuntimeError:
            pass
    finally:
        hwpx.try_register_file_path_security_module = original
    assert all_quit(), "남은 한글(Hwp.exe)이 있음"
    assert balanced(), f"CoInitialize {S.coinit} / CoUninitialize {S.couninit}"


# ------------------------------------------------------------------ 3. PDF: Open 실패
@check("3 PDF: Open 이 False 면 빈 문서를 PDF로 내보내지 않고 실패로 알린다")
def _(tmp):
    S.open_result = False
    (src,) = make_files(tmp, ["a.hwp"])
    ok, bad = pdfconv.convert_files([src], tmp / "out")
    assert not ok and [n for n, _ in bad] == ["a.hwp"], f"ok={ok} bad={bad}"
    assert not (tmp / "out" / "a.pdf").exists(), "빈 문서 PDF 가 만들어짐"


@check("3 PDF: Open 이 True 여도 문서가 비어 있으면(Path 빈 값) 실패")
def _(tmp):
    S.path_empty = True
    (src,) = make_files(tmp, ["a.hwp"])
    ok, bad = pdfconv.convert_files([src], tmp / "out")
    assert not ok and bad, f"ok={ok} bad={bad}"


@check("3 PDF(runner): 일부 실패 시 failed=[{name,error}] 이고 메시지에 실패 수")
def _(tmp):
    srcs = make_files(tmp, ["a.hwp", "b.hwp"])
    calls = {"n": 0}

    def on_open(_name):
        calls["n"] += 1
        S.open_result = calls["n"] != 2

    S.on_open = on_open
    code, result, progress, err = run_runner(
        "hwp_to_pdf_converter", {"inputs": [str(p) for p in srcs], "output": str(tmp / "out")}
    )
    assert code == 0, err
    assert result["failed"] and result["failed"][0]["name"] == "b.hwp" and result["failed"][0]["error"], result
    assert "1개는 변환하지 못했습니다" in result["message"], result["message"]


# ------------------------------------------------------------------ 4. 취합: InsertFile 실패
@check("4 취합: InsertFile 이 False 인 파일은 failed 로 알리고 나머지는 계속")
def _(tmp):
    srcs = make_files(tmp, ["a.hwp", "b.hwp", "c.hwpx"])
    S.insert_fail = {"b.hwp"}
    result = collector.merge_han_files(srcs, tmp / "out.hwpx")
    assert isinstance(result, dict), f"결과를 돌려주지 않음: {result!r}"
    assert [f["name"] for f in result["failed"]] == ["b.hwp"], result
    assert result["inserted"] == ["a.hwp", "c.hwpx"], result
    assert S.hwps[0].opened == ["a.hwp"] and S.hwps[0].inserted == ["c.hwpx"], (S.hwps[0].opened, S.hwps[0].inserted)
    assert "BreakPage" not in S.hwps[0].actions, "쪽 나누기를 넣음(구역이 나뉘므로 필요 없음)"
    assert (tmp / "out.hwpx").exists()


@check("4 취합(runner): 메시지가 완료라고 하지 않고 빠진 개수를 말한다")
def _(tmp):
    srcs = make_files(tmp, ["a.hwp", "b.hwp", "c.hwp"])
    S.insert_fail = {"b.hwp"}
    code, result, progress, err = run_runner(
        "hwp_collector", {"inputs": [str(p) for p in srcs], "output": str(tmp / "out.hwpx")}
    )
    assert code == 0, err
    assert "완료" not in result["message"], result["message"]
    assert "1개는 넣지 못해 빠졌습니다" in result["message"], result["message"]
    assert result["failed"] == [{"name": "b.hwp", "error": result["failed"][0]["error"]}] and result["failed"][0]["error"]


@check("4 취합: 모두 실패하면 빈 문서를 저장하지 않고 오류")
def _(tmp):
    srcs = make_files(tmp, ["a.hwp", "b.hwp"])
    S.open_fail = {"a.hwp", "b.hwp"}
    raised = False
    try:
        collector.merge_han_files(srcs, tmp / "out.hwpx")
    except Exception:
        raised = True
    assert raised, "오류 없이 끝남"
    assert not (tmp / "out.hwpx").exists(), "빈 결과 파일을 저장함"
    assert all_quit() and balanced()


# ------------------------------------------------------------------ 5. 취합: 저장 형식
@check("5 취합: .hwpx 로 저장하면 HWPX(ZIP) 형식으로 저장")
def _(tmp):
    srcs = make_files(tmp, ["a.hwp", "b.hwp"])
    collector.merge_han_files(srcs, tmp / "out.hwpx")
    data = (tmp / "out.hwpx").read_bytes()
    assert data.startswith(b"PK"), f"hwpx 안에 HWP 이진 형식이 들어감: {data[:8]!r} saved={S.hwps[0].saved}"
    assert all(fmt == "HWPX" for _, fmt in S.hwps[0].saved), S.hwps[0].saved


@check("5 취합: .hwp 로 저장하면 HWP 형식")
def _(tmp):
    srcs = make_files(tmp, ["a.hwp"])
    collector.merge_han_files(srcs, tmp / "out.hwp")
    assert S.hwps[0].saved and S.hwps[0].saved[0][1] == "HWP", S.hwps[0].saved


# ------------------------------------------------------------------ 6. 보안 모듈
def _security_cases(tmp, tool, payload_extra=None):
    """(a) FilePathCheckerModule 만 있는 PC: 그것을 등록, 창은 숨김.
       (b) 보안 모듈이 없는 PC: 창을 보이고 [허용] 안내가 앱까지 간다."""
    S.reset()
    S.accepted_modules = {"FilePathCheckerModule"}
    (tmp / "a").mkdir()
    srcs = make_files(tmp / "a", ["x.hwp"])
    payload = {"inputs": [str(p) for p in srcs], **(payload_extra(tmp / "a") if payload_extra else {})}
    code, result, progress, err = run_runner(tool, payload)
    assert code == 0, err
    assert "FilePathCheckerModule" in S.hwps[0].registered, f"등록 시도: {S.hwps[0].registered}"
    assert True not in S.hwps[0].visible, "보안 모듈이 있는데 창을 보임"
    assert not any(HINT in line for line in progress), progress

    S.reset()
    S.accepted_modules = set()
    (tmp / "b").mkdir()
    srcs = make_files(tmp / "b", ["y.hwp"])
    payload = {"inputs": [str(p) for p in srcs], **(payload_extra(tmp / "b") if payload_extra else {})}
    code, result, progress, err = run_runner(tool, payload)
    assert code == 0, err
    assert S.hwps[0].visible and S.hwps[0].visible[-1] is True, f"창을 보이지 않음: {S.hwps[0].visible}"
    assert any(HINT in line for line in progress), f"[허용] 안내가 앱으로 가지 않음: {progress}"


@check("6 취합: 보안 모듈 여러 이름 시도 / 없으면 창 보이기 + 안내")
def _(tmp):
    _security_cases(tmp, "hwp_collector", lambda d: {"output": str(d / "out.hwpx")})


@check("6 PDF: 보안 모듈 여러 이름 시도 / 없으면 창 보이기 + 안내")
def _(tmp):
    _security_cases(tmp, "hwp_to_pdf_converter", lambda d: {"output": str(d / "out")})


@check("6 HWPX: 보안 모듈 없으면 창 보이기 + 안내가 앱까지 전달")
def _(tmp):
    _security_cases(tmp, "hwp_to_hwpx_converter", lambda d: {"confirmed": True})


@check("6 HWPX: 원본을 지우는 도구라 확인 없이 부르면 아무것도 바꾸지 않고 거절")
def _(tmp):
    srcs = make_files(tmp, ["a.hwp"])
    code, result, progress, err = run_runner("hwp_to_hwpx_converter", {"inputs": [str(p) for p in srcs]})
    assert code != 0 or result.get("ok") is False, (code, result)
    assert (tmp / "a.hwp").exists() and not (tmp / "a.hwpx").exists()


# ------------------------------------------------------------------ 7. 중지
def _cancel_after_first(tmp, hook_name):
    cancel_file = tmp / "cancel.flag"
    seen = {"n": 0}

    def hook(_name):
        seen["n"] += 1
        if seen["n"] == 1:
            cancel_file.write_text("1")

    setattr(S, hook_name, hook)
    return cancel_file


@check("7 취합: 중지하면 넣은 것까지만 저장하고 멈춘다")
def _(tmp):
    srcs = make_files(tmp, ["a.hwp", "b.hwp", "c.hwp"])
    cancel_file = _cancel_after_first(tmp, "on_open")
    code, result, progress, err = run_runner(
        "hwp_collector", {"inputs": [str(p) for p in srcs], "output": str(tmp / "out.hwpx")}, cancel_file
    )
    assert code == 0, err
    assert result.get("stopped") is True, result
    assert S.hwps[0].opened == ["a.hwp"] and S.hwps[0].inserted == [], (S.hwps[0].opened, S.hwps[0].inserted)
    assert (tmp / "out.hwpx").exists() and "중지" in result["message"], result
    assert all_quit() and balanced()


@check("7 PDF: 중지하면 남은 파일은 건너뛰고 멈춘다")
def _(tmp):
    srcs = make_files(tmp, ["a.hwp", "b.hwp", "c.hwp"])
    cancel_file = _cancel_after_first(tmp, "on_open")
    code, result, progress, err = run_runner(
        "hwp_to_pdf_converter", {"inputs": [str(p) for p in srcs], "output": str(tmp / "out")}, cancel_file
    )
    assert code == 0, err
    assert result.get("stopped") is True and "중지" in result["message"], result
    assert sorted(p.name for p in (tmp / "out").iterdir()) == ["a.pdf"]
    assert all_quit() and balanced()


@check("7 HWPX: 중지하면 남은 파일은 건드리지 않고 멈춘다")
def _(tmp):
    srcs = make_files(tmp, ["a.hwp", "b.hwp", "c.hwp"])
    cancel_file = _cancel_after_first(tmp, "on_open")
    code, result, progress, err = run_runner(
        "hwp_to_hwpx_converter", {"inputs": [str(p) for p in srcs], "confirmed": True}, cancel_file
    )
    assert code == 0, err
    assert result.get("stopped") is True and "중지" in result["message"], result
    assert (tmp / "a.hwpx").exists() and (tmp / "b.hwp").exists() and (tmp / "c.hwp").exists()
    assert not (tmp / "b.hwpx").exists()
    assert all_quit() and balanced()


# ------------------------------------------------------------------ 9. 취합: 파일마다 쪽 설정(가로·세로) 유지
@check("9 취합: 첫 파일은 새 문서에 끼워 넣지 않고 임시 복사본을 열어 시작(첫 파일 쪽 설정 유지)")
def _(tmp):
    srcs = make_files(tmp, ["세로.hwp", "가로.hwpx", "세로2.hwp"])
    before = [p.read_bytes() for p in srcs]
    collector.merge_han_files(srcs, tmp / "out.hwpx")
    h = S.hwps[0]
    assert "FileNew" not in h.actions and "New" not in h.actions, f"빈 새 문서에서 시작함: {h.actions}"
    assert h.opened == ["세로.hwp"], h.opened
    assert all(Path(op).resolve() != srcs[0].resolve() for op in h.opened_paths), "원본을 직접 엶"
    assert [p.read_bytes() for p in srcs] == before, "원본 파일이 바뀜"
    assert not any(Path(op).exists() for op in h.opened_paths), "임시 복사본이 남음"


@check("9 취합: 둘째 파일부터 '쪽 모양 유지'(KeepSection=1)로 끼워 넣고 쪽 나누기는 넣지 않음")
def _(tmp):
    srcs = make_files(tmp, ["세로.hwp", "가로.hwpx", "세로2.hwp"])
    collector.merge_han_files(srcs, tmp / "out.hwpx")
    h = S.hwps[0]
    assert h.inserted == ["가로.hwpx", "세로2.hwp"], h.inserted
    assert h.keep_section == [1, 1], f"쪽 모양 유지를 켜지 않음: {h.keep_section}"
    assert "BreakPage" not in h.actions, h.actions


@check("9 취합: 첫 파일을 열지 못하면 실패로 알리고 다음 파일로 시작")
def _(tmp):
    srcs = make_files(tmp, ["a.hwp", "b.hwp", "c.hwp"])
    S.open_fail = {"a.hwp"}
    result = collector.merge_han_files(srcs, tmp / "out.hwpx")
    h = S.hwps[0]
    assert [f["name"] for f in result["failed"]] == ["a.hwp"], result
    assert h.opened == ["b.hwp"] and h.inserted == ["c.hwp"], (h.opened, h.inserted)
    assert result["inserted"] == ["b.hwp", "c.hwp"], result

# ------------------------------------------------------------------ 8. 정리
@check("8 취합: 저장이 예외로 끝나도 한글을 끄고 CoUninitialize")
def _(tmp):
    srcs = make_files(tmp, ["a.hwp"])
    S.save_raises = True
    try:
        collector.merge_han_files(srcs, tmp / "out.hwpx")
    except Exception:
        pass
    assert all_quit() and balanced(), (S.coinit, S.couninit)


@check("8 PDF: Open 이 예외여도 한글을 끄고 CoUninitialize")
def _(tmp):
    srcs = make_files(tmp, ["a.hwp", "b.hwp"])
    S.open_raises = True
    ok, bad = pdfconv.convert_files(srcs, tmp / "out")
    assert len(bad) == 2 and len(S.hwps) == 2
    assert all_quit() and balanced(), (S.coinit, S.couninit)


@check("8 HWPX: 도중에 예외가 나도 한글을 끄고 CoUninitialize")
def _(tmp):
    srcs = make_files(tmp, ["a.hwp", "b.hwp"])

    def log(line):
        if line.startswith("[2/"):
            raise RuntimeError("log boom")

    try:
        hwpx.convert_hwp_files_to_hwpx(srcs, log=log)
    except RuntimeError:
        pass
    assert all_quit() and balanced(), (S.coinit, S.couninit)


@check("8 한글을 부르지 못해도 CoUninitialize (취합/PDF/HWPX)")
def _(tmp):
    S.progids_ok = set()
    srcs = make_files(tmp, ["a.hwp"])
    for call in (
        lambda: collector.merge_han_files(srcs, tmp / "o.hwpx"),
        lambda: pdfconv.convert_files(srcs, tmp / "out"),
        lambda: hwpx.convert_hwp_files_to_hwpx(srcs),
    ):
        try:
            call()
        except Exception:
            pass
    assert S.coinit == S.couninit == 3, (S.coinit, S.couninit)


# ------------------------------------------------------------------ 10. 모아 찍기 → 기본 인쇄로 PDF
def _pdf_via(tool: str, src: Path, out: Path):
    if tool == "pdf":
        return pdfconv.convert_with_hancom(src, out)
    return combiner.convert_with_hancom(src, out, None)


for _tool, _label in (("pdf", "한글 PDF 변환"), ("combine", "다형식 PDF 통합")):
    @check(f"10 {_label}: hwpx 의 모아 찍기(PrintMethod=4)는 0 으로 바꾼 사본으로 PDF, 원본은 그대로")
    def _(tmp, tool=_tool):
        src = make_hwpx(tmp / "모아찍기.hwpx", 4, "모아찍기.hwpx")
        before = src.read_bytes()
        ok, msg = _pdf_via(tool, src, tmp / "out.pdf")
        h = S.hwps[-1]
        assert ok and (tmp / "out.pdf").read_bytes().startswith(b"%PDF"), msg
        assert h.opened_print == [0], f"열 때 인쇄 방식: {h.opened_print}"
        assert src.read_bytes() == before, "원본 파일이 바뀜"

    @check(f"10 {_label}: hwp 는 hwpx 로 저장해 보고 모아 찍기면 0 으로 바꾼 사본을 다시 열어 PDF")
    def _(tmp, tool=_tool):
        S.print_method = 4
        src = make_files(tmp, ["모아찍기.hwp"])[0]
        before = src.read_bytes()
        ok, msg = _pdf_via(tool, src, tmp / "out.pdf")
        h = S.hwps[-1]
        assert ok, msg
        assert [fmt for _p, fmt in h.saved if str(fmt).upper().startswith("HWPX")], f"hwpx 로 저장해 보지 않음: {h.saved}"
        assert h.opened_print[-1] == 0 and len(h.opened) == 2, f"다시 연 사본의 인쇄 방식: {h.opened_print}"
        # 한글이 쥐고 있는 print_check.hwpx 는 덮어쓸 수 없어, 고친 내용은 새 파일로 써서 연다.
        assert Path(h.opened_paths[-1]).name == "print_fixed.hwpx", h.opened_paths
        assert src.read_bytes() == before

    @check(f"10 {_label}: 기본 인쇄 문서는 예전처럼 한 번만 열고 사본도 바꾸지 않음")
    def _(tmp, tool=_tool):
        S.print_method = 0
        src = make_files(tmp, ["보통.hwp"])[0]
        ok, msg = _pdf_via(tool, src, tmp / "out.pdf")
        assert ok and len(S.hwps[-1].opened) == 1, (msg, S.hwps[-1].opened)
        plain = make_hwpx(tmp / "보통.hwpx", 0, "보통.hwpx")
        ok, msg = _pdf_via(tool, plain, tmp / "out2.pdf")
        assert ok and S.hwps[-1].opened_print == [0], (msg, S.hwps[-1].opened_print)


@check("10 인쇄 방식 바꾸기: mimetype 맨 앞 무압축, 다른 항목·압축은 그대로, 없으면 손대지 않음")
def _(tmp):
    import zipfile
    for module in (pdfconv, combiner):
        path = make_hwpx(tmp / f"{module.__name__}.hwpx", 6, "x")
        assert module.reset_hwpx_print_method(path) is True
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            assert infos[0].filename == "mimetype" and infos[0].compress_type == zipfile.ZIP_STORED
            assert [i.filename for i in infos] == ["mimetype", "version.xml", "settings.xml", "Contents/section0.xml"]
            assert z.read("Contents/section0.xml") == b"<sec> source x</sec>"
            settings = z.read("settings.xml").decode()
            assert 'name="PrintMethod" type="short">0<' in settings and 'name="ZoomX" type="short">100<' in settings
        assert module.reset_hwpx_print_method(path) is False, "이미 0 이면 다시 쓰지 않음"
        held = make_hwpx(tmp / f"{module.__name__}_held.hwpx", 4, "x")
        held_before = held.read_bytes()
        fixed = tmp / f"{module.__name__}_fixed.hwpx"
        assert module.reset_hwpx_print_method(held, fixed) is True
        assert held.read_bytes() == held_before, "dest 를 주면 원래 파일은 그대로"
        assert print_method_of(fixed) == 0
        none = make_hwpx(tmp / f"{module.__name__}_none.hwpx", None, "x")
        before = none.read_bytes()
        assert module.reset_hwpx_print_method(none) is False and none.read_bytes() == before
        broken = tmp / "broken.hwpx"
        broken.write_bytes(b"PK not a zip")
        assert module.reset_hwpx_print_method(broken) is False


# ------------------------------------------------------------------ 결과
failures = 0
for name, ok, detail in RESULTS:
    print(("✔ " if ok else "✗ ") + name)
    if not ok:
        failures += 1
        for line in detail.strip().splitlines():
            print("    " + line)
print(f"\n{len(RESULTS) - failures}/{len(RESULTS)} 통과")
sys.exit(1 if failures else 0)
