"""한글 용량 압축(hwp_compress) 시험. 저장소 루트에서:

    python tests/regression/test_hwp_compress.py

가짜 hwpx(그림을 넣은 ZIP)를 그때그때 만들어 앱이 부르는 그대로(bridge/runner.py) 돌린다.
옛 한글(hwp)은 가짜 한글(COM) 개체로 hwpx 변환을 흉내 낸다. 개인 자료는 쓰지 않는다.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import random
import sys
import tempfile
import traceback
import types
import zipfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
PROGRESS = "@@JBEDU_PROGRESS@@"
HINT = "한글이 파일 접근을 물으면 [허용]을 눌러 주세요."
SECTION_XML = ('<?xml version="1.0" encoding="UTF-8"?><hs:sec xmlns:hs="x" xmlns:hp="y">'
               '<hp:p><hp:run><hp:t>가짜 문서 본문</hp:t></hp:run>'
               '<hp:pic><hc:img binaryItemIDRef="image1"/></hp:pic></hp:p></hs:sec>').encode("utf-8")
HPF = ('<?xml version="1.0" encoding="UTF-8"?><opf:package xmlns:opf="z"><opf:manifest>'
       '<opf:item id="image1" href="BinData/image1.jpg" media-type="image/jpg"/>'
       '</opf:manifest></opf:package>').encode("utf-8")


# ------------------------------------------------------------------ 가짜 그림·문서
def noisy(size, mode="RGB", seed=1) -> Image.Image:
    rnd = random.Random(seed)
    w, h = size
    small = Image.new(mode, (max(1, w // 8), max(1, h // 8)))
    px = small.load()
    for y in range(small.size[1]):
        for x in range(small.size[0]):
            if mode == "RGBA":
                px[x, y] = (rnd.randrange(256), rnd.randrange(256), rnd.randrange(256), rnd.randrange(80, 256))
            else:
                px[x, y] = (rnd.randrange(256), rnd.randrange(256), rnd.randrange(256))
    return small.resize(size, Image.BICUBIC)


def img_bytes(img: Image.Image, fmt: str, **kw) -> bytes:
    b = io.BytesIO()
    img.save(b, fmt, **kw)
    return b.getvalue()


def animated_gif() -> bytes:
    frames = [noisy((2400, 1800), seed=i).convert("P") for i in range(2)]
    b = io.BytesIO()
    frames[0].save(b, "GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    return b.getvalue()


def exif_rotated_jpeg() -> bytes:
    img = noisy((3000, 2000), seed=7)
    exif = Image.Exif()
    exif[0x0112] = 6   # 시계 방향 90도로 보여야 하는 사진
    return img_bytes(img, "JPEG", quality=95, exif=exif.tobytes())


def make_hwpx(path: Path, images: dict[str, bytes] | None = None, extra: dict[str, bytes] | None = None,
              mimetype: bytes = b"application/hwp+zip") -> Path:
    images = images if images is not None else {
        "BinData/image1.jpg": img_bytes(noisy((4000, 3000), seed=1), "JPEG", quality=95),
        "BinData/image2.png": img_bytes(noisy((300, 200), seed=2), "PNG"),
        "BinData/image3.png": img_bytes(noisy((3000, 2000), "RGBA", seed=3), "PNG"),
        "BinData/image4.gif": animated_gif(),
        "BinData/image5.bmp": img_bytes(noisy((2600, 1800), seed=5), "BMP"),
    }
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), mimetype)  # 압축 안 함(ZIP_STORED)
        z.writestr("version.xml", b'<?xml version="1.0"?><hv:HCFVersion xmlns:hv="v"/>', zipfile.ZIP_DEFLATED)
        z.writestr("Contents/content.hpf", HPF, zipfile.ZIP_DEFLATED)
        z.writestr("Contents/section0.xml", SECTION_XML, zipfile.ZIP_DEFLATED)
        z.writestr("Preview/PrvImage.png", img_bytes(noisy((2000, 2000), seed=9), "PNG"), zipfile.ZIP_DEFLATED)
        z.writestr("META-INF/manifest.xml", b'<?xml version="1.0"?><odf:manifest xmlns:odf="m"/>', zipfile.ZIP_DEFLATED)
        for name, data in images.items():
            z.writestr(name, data, zipfile.ZIP_STORED)
        for name, data in (extra or {}).items():
            z.writestr(name, data, zipfile.ZIP_DEFLATED)
    return path


def entries(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist()}


def size_of(data: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(data)) as im:
        return im.size


# ------------------------------------------------------------------ 가짜 한글(COM)
class Fake:
    def reset(self):
        self.hwps = []
        self.accepted = {"SecurityModule"}
        self.coinit = 0
        self.couninit = 0
        self.source_for_hwp: Path | None = None   # SaveAs 가 써 줄 hwpx
        self.open_ok = True


F = Fake()
F.reset()


class FakeHwp:
    def __init__(self):
        self.visible = []
        self.quit = False
        self.opened = []
        w = types.SimpleNamespace()
        hwp = self

        class Win:
            @property
            def Visible(self):
                return hwp.visible[-1] if hwp.visible else False

            @Visible.setter
            def Visible(self, v):
                hwp.visible.append(bool(v))

        win = Win()
        w.Item = lambda _i: win
        self.XHwpWindows = w

    def RegisterModule(self, _k, name):
        return name in F.accepted

    def Open(self, path, fmt="", opt=""):
        self.opened.append(path)
        return F.open_ok

    def SaveAs(self, path, fmt=None, arg=None):
        Path(path).write_bytes(F.source_for_hwp.read_bytes())
        return True

    def Clear(self, _n):
        return True

    def Quit(self):
        self.quit = True


def _dispatch(prog_id, *_a, **_k):
    if prog_id != "HWPFrame.HwpObject":
        raise Exception("잘못된 클래스 문자열")
    h = FakeHwp()
    F.hwps.append(h)
    return h


def install_stubs():
    pythoncom = types.ModuleType("pythoncom")
    pythoncom.CoInitialize = lambda: setattr(F, "coinit", F.coinit + 1)
    pythoncom.CoUninitialize = lambda: setattr(F, "couninit", F.couninit + 1)
    win32com = types.ModuleType("win32com")
    client = types.ModuleType("win32com.client")
    dynamic = types.ModuleType("win32com.client.dynamic")
    dynamic.Dispatch = _dispatch

    def no_cache(*_a, **_k):
        raise AttributeError("module 'win32com.gen_py.x' has no attribute 'CLSIDToPackageMap'")

    client.Dispatch = no_cache
    client.dynamic = dynamic
    win32com.client = client
    sys.modules.update({"pythoncom": pythoncom, "win32com": win32com,
                        "win32com.client": client, "win32com.client.dynamic": dynamic})


install_stubs()
sys.path.insert(0, str(ROOT / "bridge"))
os.environ["JBEDU_TOOLS_ROOT"] = str(ROOT / "tools")
os.environ["JBEDU_PROJECT_ROOT"] = str(ROOT / "tools")
os.environ.pop("JBEDU_CANCEL_FILE", None)
import runner  # noqa: E402


def run(payload: dict, cancel_file: Path | None = None):
    if cancel_file is not None:
        os.environ["JBEDU_CANCEL_FILE"] = str(cancel_file)
    out, err = io.StringIO(), io.StringIO()
    argv = sys.argv
    sys.argv = ["runner", "--tool", "hwp_compress", "--payload", json.dumps(payload, ensure_ascii=False)]
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = runner.main()
    finally:
        sys.argv = argv
        os.environ.pop("JBEDU_CANCEL_FILE", None)
    lines = [ln for ln in out.getvalue().splitlines() if ln.strip()]
    progress = [ln[len(PROGRESS):] for ln in lines if ln.startswith(PROGRESS)]
    others = [ln for ln in lines if not ln.startswith(PROGRESS)]
    assert len(others) <= 1, f"stdout 에 JSON 말고 다른 것이 있음: {others[:3]}"
    result = json.loads(others[-1]) if others else None
    return code, result, progress, err.getvalue()


RESULTS: list[tuple[str, bool, str]] = []


def check(name):
    def deco(fn):
        F.reset()
        with tempfile.TemporaryDirectory() as tmp:
            try:
                fn(Path(tmp))
                RESULTS.append((name, True, ""))
            except Exception as error:
                detail = f"{type(error).__name__}: {error}"
                if not isinstance(error, AssertionError):
                    detail += "\n" + traceback.format_exc(limit=4)
                RESULTS.append((name, False, detail))
        return fn
    return deco


# ------------------------------------------------------------------ 시험
@check("용량 우선: 큰 그림만 줄이고 본문·다른 항목·원본은 그대로, 결과는 _용량축소.hwpx")
def _(tmp):
    src = make_hwpx(tmp / "보고서.hwpx")
    before = src.read_bytes()
    code, result, progress, err = run({"inputs": [str(src)], "mode": "standard"})
    assert code == 0, err
    out = tmp / "보고서_용량축소.hwpx"
    assert out.exists(), result
    assert src.read_bytes() == before, "원본이 바뀜"
    a, b = entries(src), entries(out)
    assert set(a) == set(b), set(a) ^ set(b)
    for n in ("version.xml", "Contents/content.hpf", "Contents/section0.xml", "Preview/PrvImage.png",
              "META-INF/manifest.xml", "BinData/image2.png", "BinData/image4.gif"):
        assert a[n] == b[n], f"바뀌면 안 되는 항목이 바뀜: {n}"
    assert max(size_of(b["BinData/image1.jpg"])) == 1600, size_of(b["BinData/image1.jpg"])
    assert max(size_of(b["BinData/image3.png"])) == 1600
    assert max(size_of(b["BinData/image5.bmp"])) == 1600
    with Image.open(io.BytesIO(b["BinData/image3.png"])) as im:
        assert im.mode == "RGBA", f"투명한 PNG 의 투명도가 사라짐: {im.mode}"
    with zipfile.ZipFile(out) as z:
        first = z.infolist()[0]
        assert first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED
        assert z.testzip() is None
    assert out.stat().st_size < src.stat().st_size
    assert result["popup"]["level"] == "success", result["popup"]
    assert "줄임" in result["popup"]["message"], result["popup"]["message"]


@check("화질 우선: 긴 변 2560px 까지 둔다")
def _(tmp):
    src = make_hwpx(tmp / "a.hwpx")
    code, result, _, err = run({"inputs": [str(src)], "mode": "quality"})
    assert code == 0, err
    b = entries(tmp / "a_용량축소.hwpx")
    assert max(size_of(b["BinData/image1.jpg"])) == 2560


@check("사진의 회전 정보(EXIF)대로 돌려 저장(원본 프로그램과 같음)")
def _(tmp):
    src = make_hwpx(tmp / "a.hwpx", images={"BinData/image1.jpg": exif_rotated_jpeg()})
    code, result, _, err = run({"inputs": [str(src)], "mode": "standard"})
    assert code == 0, err
    w, h = size_of(entries(tmp / "a_용량축소.hwpx")["BinData/image1.jpg"])
    assert h > w and max(w, h) == 1600, (w, h)


@check("목표 용량: 이미 목표 이하면 그림을 줄이지 않고 그대로 저장")
def _(tmp):
    src = make_hwpx(tmp / "a.hwpx")
    code, result, _, err = run({"inputs": [str(src)], "mode": "target", "target_mb": 500})
    assert code == 0, err
    out = tmp / "a_용량축소.hwpx"
    assert out.read_bytes() == src.read_bytes()
    assert result["results"][0]["target_reached"] is True
    assert "목표 용량 이하" in result["popup"]["message"]


@check("목표 용량: 단계별로 줄여 목표에 닿으면 멈추고, 못 닿으면 '목표 미달' 경고")
def _(tmp):
    src = make_hwpx(tmp / "a.hwpx")
    code, result, progress, err = run({"inputs": [str(src)], "mode": "target", "target_mb": 0.01})
    assert code == 0, err
    r = result["results"][0]
    assert r["target_reached"] is False and r["output_bytes"] < r["original_bytes"], r
    assert any("4/4단계" in p for p in progress), progress
    assert result["popup"]["level"] == "warning" and "목표 미달" in result["popup"]["message"], result["popup"]
    b = entries(tmp / "a_용량축소.hwpx")
    assert max(size_of(b["BinData/image1.jpg"])) == 1280, "가장 작은 단계(1280px) 결과를 고르지 않음"


@check("목표 용량: 0 이나 글자를 넣으면 알기 쉬운 오류")
def _(tmp):
    src = make_hwpx(tmp / "a.hwpx")
    code, _, _, err = run({"inputs": [str(src)], "mode": "target", "target_mb": 0})
    assert code == 1 and "0보다 크게" in err, err
    code, _, _, err = run({"inputs": [str(src)], "mode": "target", "target_mb": "abc"})
    assert code == 1 and "숫자" in err, err


@check("전자서명·암호가 있는 문서, hwpx 가 아닌 파일은 건드리지 않고 이유를 알림")
def _(tmp):
    signed = make_hwpx(tmp / "서명.hwpx", extra={"META-INF/signatures/sig.xml": b"<sig/>"})
    locked = tmp / "암호.hwpx"
    make_hwpx(locked)
    data = entries(locked)
    data["META-INF/manifest.xml"] = b'<odf:manifest><odf:encryption-data/></odf:manifest>'
    with zipfile.ZipFile(locked, "w") as z:
        for n, d in data.items():
            z.writestr(n, d)
    broken = tmp / "깨짐.hwpx"
    broken.write_bytes(b"PK\x03\x04 not a zip")
    good = make_hwpx(tmp / "정상.hwpx")
    code, result, _, err = run({"inputs": [str(p) for p in (signed, locked, broken, good)], "mode": "standard"})
    assert code == 0, err
    reasons = {f["name"]: f["error"] for f in result["failed"]}
    assert "전자서명" in reasons.get("서명.hwpx", ""), reasons
    assert "암호" in reasons.get("암호.hwpx", ""), reasons
    assert "손상" in reasons.get("깨짐.hwpx", ""), reasons
    assert [r["name"] for r in result["results"]] == ["정상.hwpx"]
    assert not (tmp / "서명_용량축소.hwpx").exists() and not (tmp / "암호_용량축소.hwpx").exists()
    assert result["popup"]["level"] == "warning"
    assert "3개는 처리하지 못했습니다" in result["message"], result["message"]


@check("같은 이름의 결과가 있으면 (1)을 붙여 덮어쓰지 않음, 저장 폴더를 고르면 거기에 저장")
def _(tmp):
    src = make_hwpx(tmp / "a.hwpx")
    (tmp / "a_용량축소.hwpx").write_bytes(b"old")
    code, result, _, err = run({"inputs": [str(src)], "mode": "standard"})
    assert code == 0, err
    assert (tmp / "a_용량축소.hwpx").read_bytes() == b"old"
    assert (tmp / "a_용량축소(1).hwpx").exists()
    out_dir = tmp / "결과 폴더"
    code, result, _, err = run({"inputs": [str(src)], "mode": "standard", "output": str(out_dir)})
    assert code == 0, err
    assert (out_dir / "a_용량축소.hwpx").exists()


@check("옛 한글(hwp): 한글로 hwpx 로 바꾼 뒤 줄여 .hwpx 로 저장, 원본 hwp 는 그대로, 한글은 끔")
def _(tmp):
    F.source_for_hwp = make_hwpx(tmp / "_converted_source.hwpx")
    hwp = tmp / "공문.hwp"
    hwp.write_bytes(b"\xd0\xcf\x11\xe0 fake hwp body")
    before = hwp.read_bytes()
    code, result, progress, err = run({"inputs": [str(hwp)], "mode": "standard"})
    assert code == 0, err
    out = tmp / "공문_용량축소.hwpx"
    assert out.exists() and out.read_bytes()[:2] == b"PK"
    assert hwp.read_bytes() == before
    assert max(size_of(entries(out)["BinData/image1.jpg"])) == 1600
    assert len(F.hwps) == 1 and F.hwps[0].quit, "한글을 끄지 않음"
    assert F.coinit == F.couninit == 1
    assert all(Path(p).resolve() != hwp.resolve() for p in F.hwps[0].opened), "원본 hwp 를 직접 엶"
    assert result["results"][0]["converted"] is True
    assert "hwp를 hwpx로 바꿔 저장" in result["popup"]["message"]
    assert not any(HINT in p for p in progress)


@check("옛 한글(hwp) 여러 개: 한글은 한 번만 띄우고, 보안 모듈이 없으면 창을 보이고 [허용] 안내")
def _(tmp):
    F.source_for_hwp = make_hwpx(tmp / "_src.hwpx")
    F.accepted = set()
    files = []
    for n in ("1.hwp", "2.hwp"):
        p = tmp / n
        p.write_bytes(b"\xd0\xcf\x11\xe0 fake")
        files.append(p)
    code, result, progress, err = run({"inputs": [str(p) for p in files], "mode": "standard"})
    assert code == 0, err
    assert len(F.hwps) == 1, f"한글을 {len(F.hwps)}번 띄움"
    assert F.hwps[0].visible and F.hwps[0].visible[-1] is True
    assert any(HINT in p for p in progress), progress
    assert len(result["results"]) == 2


@check("옛 한글(hwp)을 한글이 열지 못하면 그 파일만 실패로 알리고 한글은 끔")
def _(tmp):
    F.source_for_hwp = make_hwpx(tmp / "_src.hwpx")
    F.open_ok = False
    hwp = tmp / "x.hwp"
    hwp.write_bytes(b"\xd0\xcf\x11\xe0 fake")
    good = make_hwpx(tmp / "y.hwpx")
    code, result, _, err = run({"inputs": [str(hwp), str(good)], "mode": "standard"})
    assert code == 0, err
    assert [f["name"] for f in result["failed"]] == ["x.hwp"] and "열지 못했습니다" in result["failed"][0]["error"]
    assert [r["name"] for r in result["results"]] == ["y.hwpx"]
    assert F.hwps[0].quit and F.coinit == F.couninit


@check("중지: 중지 신호가 있으면 저장하지 않고 멈춤")
def _(tmp):
    src = make_hwpx(tmp / "a.hwpx")
    flag = tmp / "stop.flag"
    flag.write_text("1")
    code, result, _, err = run({"inputs": [str(src)], "mode": "standard"}, cancel_file=flag)
    assert code == 0, err
    assert result["stopped"] is True and result["popup"]["level"] == "warning", result
    assert not (tmp / "a_용량축소.hwpx").exists()
    assert not list(tmp.glob("*.part"))


@check("줄일 그림이 없으면 그대로 저장하고 그렇게 알림")
def _(tmp):
    src = make_hwpx(tmp / "a.hwpx", images={"BinData/image1.png": img_bytes(noisy((200, 100)), "PNG")})
    code, result, _, err = run({"inputs": [str(src)], "mode": "standard"})
    assert code == 0, err
    assert (tmp / "a_용량축소.hwpx").read_bytes() == src.read_bytes()
    assert "그대로" in result["popup"]["message"], result["popup"]["message"]


if __name__ == "__main__":
    for name, ok, detail in RESULTS:
        print(("✔ " if ok else "✗ ") + name)
        if not ok:
            print("   " + detail.replace("\n", "\n   "))
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n{passed}/{len(RESULTS)} 통과")
    sys.exit(0 if passed == len(RESULTS) else 1)
