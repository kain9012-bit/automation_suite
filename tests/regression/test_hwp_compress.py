"""한글 용량 압축(hwp_compress) 시험. 저장소 루트에서:

    python tests/regression/test_hwp_compress.py

가짜 hwpx(그림 개체·표 칸 배경 그림을 넣은 ZIP)를 그때그때 만들어 앱이 부르는 그대로(bridge/runner.py) 돌린다.
옛 한글(hwp)은 가짜 한글(COM) 개체로 hwpx 변환을 흉내 낸다. 개인 자료는 쓰지 않는다.

단위: imgDim·imgClip = 그림 픽셀 × 75, curSz·cellSz = 1/7200 인치. 150dpi 로 1인치 = 150픽셀.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import random
import re
import sys
import tempfile
import traceback
import types
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
PROGRESS = "@@JBEDU_PROGRESS@@"
HINT = "한글이 파일 접근을 물으면 [허용]을 눌러 주세요."
INCH = 7200


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


def pic(ref: str, px: tuple[int, int], show_in: tuple[float, float], clip_px=None, img_first=False) -> str:
    """그림 개체 하나. px: 그림 픽셀, show_in: 문서에 보이는 크기(인치), clip_px: 보이는 부분(left, right, top, bottom 픽셀)."""
    w, h = px
    cl, cr, ct, cb = clip_px or (0, w, 0, h)
    sw, sh = int(show_in[0] * INCH), int(show_in[1] * INCH)
    img = f'<hc:img binaryItemIDRef="{ref}" bright="0" contrast="0" effect="REAL_PIC" alpha="0"/>'
    return (f'<hp:pic id="1" zOrder="0" numberingType="PICTURE" reverse="0" href="" groupLevel="0" instid="1">'
            f'<hp:offset x="0" y="0"/><hp:orgSz width="{sw}" height="{sh}"/><hp:curSz width="{sw}" height="{sh}"/>'
            f'<hp:flip horizontal="0" vertical="0"/><hp:rotationInfo angle="0" centerX="0" centerY="0" rotateimage="1"/>'
            f'<hp:renderingInfo><hc:transMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/></hp:renderingInfo>'
            + (img if img_first else "")
            + f'<hp:imgRect><hc:pt0 x="0" y="0"/><hc:pt1 x="{sw}" y="0"/><hc:pt2 x="{sw}" y="{sh}"/><hc:pt3 x="0" y="{sh}"/></hp:imgRect>'
            f'<hp:imgClip left="{cl * 75}" right="{cr * 75}" top="{ct * 75}" bottom="{cb * 75}"/>'
            f'<hp:inMargin left="0" right="0" top="0" bottom="0"/>'
            f'<hp:imgDim dimwidth="{w * 75}" dimheight="{h * 75}"/>'
            + ("" if img_first else img)
            + f'<hp:effects/><hp:sz width="{sw}" widthRelTo="ABSOLUTE" height="{sh}" heightRelTo="ABSOLUTE" protect="0"/>'
            f'<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" '
            f'vertRelTo="PARA" horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
            f'<hp:outMargin left="0" right="0" top="0" bottom="0"/></hp:pic>')


def cell(border_fill: str, size_in: tuple[float, float]) -> str:
    w, h = int(size_in[0] * INCH), int(size_in[1] * INCH)
    return (f'<hp:tbl rowCnt="1" colCnt="1"><hp:tr><hp:tc name="" header="0" hasMargin="0" protect="0" '
            f'editable="0" dirty="0" borderFillIDRef="{border_fill}"><hp:subList><hp:p><hp:run><hp:t>칸</hp:t>'
            f'</hp:run></hp:p></hp:subList><hp:cellAddr colAddr="0" rowAddr="0"/><hp:cellSpan colSpan="1" rowSpan="1"/>'
            f'<hp:cellSz width="{w}" height="{h}"/></hp:tc></hp:tr></hp:tbl>')


def border_fill(bf_id: str, ref: str, mode: str = "TOTAL") -> str:
    return (f'<hh:borderFill id="{bf_id}" threeD="0" shadow="0"><hc:fillBrush><hc:imgBrush mode="{mode}">'
            f'<hc:img binaryItemIDRef="{ref}" bright="0" contrast="0" effect="REAL_PIC" alpha="0"/>'
            f'</hc:imgBrush></hc:fillBrush></hh:borderFill>')


def make_hwpx(path: Path, images: dict[str, bytes] | None = None, body: str | None = None,
              fills: str = "", extra: dict[str, bytes] | None = None,
              mimetype: bytes = b"application/hwp+zip") -> Path:
    """images: {'BinData/imageN.ext': 그림}. 항목 id 는 파일 이름(imageN). body 를 주지 않으면 그림마다
    실제 크기의 1/4(4000px → 보이는 크기 1000px÷150dpi 가 아니라 4인치)로 하나씩 넣는다."""
    if images is None:
        images = {"BinData/image1.jpg": img_bytes(noisy((4000, 3000), seed=1), "JPEG", quality=95)}
    if body is None:
        body = "".join(pic(Path(n).stem, size_of(d), (4, 4 * size_of(d)[1] / size_of(d)[0])) for n, d in images.items())
    items = "".join(f'<opf:item id="{Path(n).stem}" href="{n}" media-type="image/{Path(n).suffix[1:]}" isEmbeded="1"/>'
                    for n in images)
    hpf = ('<?xml version="1.0" encoding="UTF-8"?><opf:package xmlns:opf="http://www.idpf.org/2007/opf/"><opf:manifest>'
           '<opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>'
           '<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>'
           f'{items}</opf:manifest></opf:package>')
    ns = ('xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core" '
          'xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"')
    header = (f'<?xml version="1.0" encoding="UTF-8"?><hh:head {ns}><hh:refList><hh:borderFills>'
              f'<hh:borderFill id="1" threeD="0" shadow="0"/>{fills}</hh:borderFills></hh:refList></hh:head>')
    section = (f'<?xml version="1.0" encoding="UTF-8"?><hs:sec {ns}><hp:p><hp:run><hp:t>가짜 문서 본문</hp:t>'
               f'</hp:run><hp:run>{body}</hp:run></hp:p></hs:sec>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), mimetype)  # 압축 안 함(ZIP_STORED)
        z.writestr("version.xml", b'<?xml version="1.0"?><hv:HCFVersion xmlns:hv="v"/>', zipfile.ZIP_DEFLATED)
        z.writestr("Contents/content.hpf", hpf.encode("utf-8"), zipfile.ZIP_DEFLATED)
        z.writestr("Contents/header.xml", header.encode("utf-8"), zipfile.ZIP_DEFLATED)
        z.writestr("Contents/section0.xml", section.encode("utf-8"), zipfile.ZIP_DEFLATED)
        z.writestr("Preview/PrvImage.png", img_bytes(noisy((200, 280), seed=9), "PNG"), zipfile.ZIP_DEFLATED)
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


def tag_attrs(xml: bytes, tag: str) -> list[dict[str, int]]:
    out = []
    for m in re.finditer(rb"<hp:" + tag.encode() + rb"\b([^>]*)/>", xml):
        out.append({k.decode(): int(v) for k, v in re.findall(rb'(\w+)="(-?\d+)"', m.group(1))})
    return out


def near(a: int, b: int, tol: int = 2) -> bool:
    return abs(a - b) <= tol


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
@check("기본 줄이기: 보이는 크기 기준 150dpi 로 줄이고, imgDim 만 새 픽셀로, 원본·다른 항목은 그대로")
def _(tmp):
    src = make_hwpx(tmp / "보고서.hwpx")      # 4000×3000 사진을 4×3인치로 → 600×450
    before = src.read_bytes()
    code, result, progress, err = run({"inputs": [str(src)]})   # 방식을 안 주면 기본 줄이기
    assert code == 0, err
    out = tmp / "보고서_용량축소.hwpx"
    assert out.exists(), result
    assert src.read_bytes() == before, "원본이 바뀜"
    a, b = entries(src), entries(out)
    assert set(a) == set(b), set(a) ^ set(b)
    for n in ("version.xml", "Contents/content.hpf", "Contents/header.xml", "Preview/PrvImage.png",
              "META-INF/manifest.xml"):
        assert a[n] == b[n], f"바뀌면 안 되는 항목이 바뀜: {n}"
    assert size_of(b["BinData/image1.jpg"]) == (600, 450), size_of(b["BinData/image1.jpg"])
    dim = tag_attrs(b["Contents/section0.xml"], "imgDim")[0]
    clip = tag_attrs(b["Contents/section0.xml"], "imgClip")[0]
    assert dim == {"dimwidth": 600 * 75, "dimheight": 450 * 75}, dim
    assert clip == {"left": 0, "right": 600 * 75, "top": 0, "bottom": 450 * 75}, clip
    # 보이는 크기·위치는 그대로(imgDim·imgClip 말고는 글자 하나 다르지 않음)
    strip = lambda x: re.sub(rb"<hp:img(Dim|Clip)\b[^>]*/>", b"", x)
    assert strip(a["Contents/section0.xml"]) == strip(b["Contents/section0.xml"])
    ElementTree.fromstring(b["Contents/section0.xml"])
    with zipfile.ZipFile(out) as z:
        first = z.infolist()[0]
        assert first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED
        assert z.testzip() is None
    assert out.stat().st_size < src.stat().st_size
    assert result["popup"]["level"] == "success", result["popup"]
    assert "그림 1개 중 1개 줄임" in result["popup"]["message"], result["popup"]["message"]


@check("기본 줄이기: 목표 용량 칸은 쓰지 않음(글자가 들어 있어도 오류 없이 기본 줄이기)")
def _(tmp):
    src = make_hwpx(tmp / "a.hwpx")
    code, result, _, err = run({"inputs": [str(src)], "target_mode": "basic", "target_mb": "abc"})
    assert code == 0, err
    assert size_of(entries(tmp / "a_용량축소.hwpx")["BinData/image1.jpg"]) == (600, 450)


@check("잘라낸 그림 영역 지우기: 보이는 부분만 남기고, imgClip 은 남은 그림 전체를 가리킴")
def _(tmp):
    data = img_bytes(noisy((4000, 3000), seed=2), "JPEG", quality=95)
    # 가운데 2000×1500 만 보이게 잘라 4×3인치로 → 잘라낸 뒤 600×450
    body = pic("image1", (4000, 3000), (4, 3), clip_px=(1000, 3000, 750, 2250))
    src = make_hwpx(tmp / "a.hwpx", images={"BinData/image1.jpg": data}, body=body)
    code, result, _, err = run({"inputs": [str(src)]})
    assert code == 0, err
    b = entries(tmp / "a_용량축소.hwpx")
    assert size_of(b["BinData/image1.jpg"]) == (600, 450), size_of(b["BinData/image1.jpg"])
    clip = tag_attrs(b["Contents/section0.xml"], "imgClip")[0]
    dim = tag_attrs(b["Contents/section0.xml"], "imgDim")[0]
    assert clip == {"left": 0, "right": 600 * 75, "top": 0, "bottom": 450 * 75}, clip
    assert dim == {"dimwidth": 600 * 75, "dimheight": 450 * 75}, dim
    # 남은 그림이 원래 보이던 부분과 같은지(가운데 색 비교)
    with Image.open(io.BytesIO(data)) as o, Image.open(io.BytesIO(b["BinData/image1.jpg"])) as n:
        want = o.crop((1000, 750, 3000, 2250)).resize((600, 450)).convert("RGB").getpixel((300, 225))
        got = n.convert("RGB").getpixel((300, 225))
        assert all(abs(x - y) < 40 for x, y in zip(want, got)), (want, got)


@check("자르기만 하고 보이는 크기가 이미 150dpi 이하인 그림: 잘라낸 부분만 지움")
def _(tmp):
    data = img_bytes(noisy((1200, 900), seed=3), "PNG")
    body = pic("image1", (1200, 900), (4, 3), clip_px=(0, 600, 0, 450))   # 600×450 을 4×3인치 = 150dpi
    src = make_hwpx(tmp / "a.hwpx", images={"BinData/image1.png": data}, body=body)
    code, result, _, err = run({"inputs": [str(src)]})
    assert code == 0, err
    b = entries(tmp / "a_용량축소.hwpx")
    assert size_of(b["BinData/image1.png"]) == (600, 450)
    assert tag_attrs(b["Contents/section0.xml"], "imgClip")[0]["right"] == 600 * 75


@check("이미 150dpi 이하로 보이는 그림은 다시 저장하지 않음(화질을 잃지 않게)")
def _(tmp):
    data = img_bytes(noisy((600, 450), seed=4), "JPEG", quality=95)
    src = make_hwpx(tmp / "a.hwpx", images={"BinData/image1.jpg": data},
                    body=pic("image1", (600, 450), (4, 3)))
    code, result, _, err = run({"inputs": [str(src)]})
    assert code == 0, err
    assert (tmp / "a_용량축소.hwpx").read_bytes() == src.read_bytes()
    assert "그대로" in result["popup"]["message"], result["popup"]["message"]


@check("한 그림을 여러 곳에 쓰면 가장 크게 보이는 곳 기준, 쓰는 곳마다 imgDim·imgClip 을 고침")
def _(tmp):
    data = img_bytes(noisy((4000, 3000), seed=5), "JPEG", quality=95)
    body = pic("image1", (4000, 3000), (2, 1.5)) + pic("image1", (4000, 3000), (6, 4.5))
    src = make_hwpx(tmp / "a.hwpx", images={"BinData/image1.jpg": data}, body=body)
    code, result, _, err = run({"inputs": [str(src)]})
    assert code == 0, err
    b = entries(tmp / "a_용량축소.hwpx")
    assert size_of(b["BinData/image1.jpg"]) == (900, 675), size_of(b["BinData/image1.jpg"])
    dims = tag_attrs(b["Contents/section0.xml"], "imgDim")
    assert dims == [{"dimwidth": 900 * 75, "dimheight": 675 * 75}] * 2, dims


@check("hc:img 가 imgRect 앞에 있는 문서(한글 버전 차이)도 찾아 줄임")
def _(tmp):
    data = img_bytes(noisy((4000, 3000), seed=6), "JPEG", quality=95)
    src = make_hwpx(tmp / "a.hwpx", images={"BinData/image1.jpg": data},
                    body=pic("image1", (4000, 3000), (4, 3), img_first=True))
    code, result, _, err = run({"inputs": [str(src)]})
    assert code == 0, err
    assert size_of(entries(tmp / "a_용량축소.hwpx")["BinData/image1.jpg"]) == (600, 450)


@check("표 칸 배경 그림(크기에 맞추어): 칸 크기 기준 150dpi 로 줄이고 자르지 않음, 바둑판식은 그대로")
def _(tmp):
    fill = img_bytes(noisy((3000, 1500), seed=7), "PNG")
    tile = img_bytes(noisy((2000, 1000), seed=8), "PNG")
    body = cell("2", (2, 1)) + cell("3", (2, 1))
    src = make_hwpx(tmp / "a.hwpx", images={"BinData/image1.png": fill, "BinData/image2.png": tile}, body=body,
                    fills=border_fill("2", "image1") + border_fill("3", "image2", mode="TILE"))
    code, result, _, err = run({"inputs": [str(src)]})
    assert code == 0, err
    a, b = entries(src), entries(tmp / "a_용량축소.hwpx")
    assert size_of(b["BinData/image1.png"]) == (300, 150), size_of(b["BinData/image1.png"])
    assert b["BinData/image2.png"] == a["BinData/image2.png"], "바둑판식 채우기 그림이 바뀜"
    assert a["Contents/header.xml"] == b["Contents/header.xml"]
    assert a["Contents/section0.xml"] == b["Contents/section0.xml"]


@check("어디에 쓰이는지 모두 알 수 없는 그림, 회전 정보 등으로 비율이 다른 그림은 건드리지 않음")
def _(tmp):
    unknown = img_bytes(noisy((4000, 3000), seed=9), "JPEG", quality=95)
    rotated = img_bytes(noisy((3000, 4000), seed=10), "JPEG", quality=95)
    body = (pic("image1", (4000, 3000), (4, 3)) + '<hp:foo><hc:img binaryItemIDRef="image1"/></hp:foo>'
            + pic("image2", (4000, 3000), (4, 3)))   # 문서에는 4000×3000 으로 적혔는데 실제는 3000×4000
    src = make_hwpx(tmp / "a.hwpx", images={"BinData/image1.jpg": unknown, "BinData/image2.jpg": rotated},
                    body=body)
    code, result, _, err = run({"inputs": [str(src)]})
    assert code == 0, err
    assert (tmp / "a_용량축소.hwpx").read_bytes() == src.read_bytes()


@check("투명 PNG 는 투명도 유지, 움직이는 GIF 는 그대로, BMP 는 BMP 로 줄임(그림 형식·이름 유지)")
def _(tmp):
    imgs = {
        "BinData/image1.png": img_bytes(noisy((3000, 2000), "RGBA", seed=11), "PNG"),
        "BinData/image2.gif": animated_gif(),
        "BinData/image3.bmp": img_bytes(noisy((2400, 1800), seed=12), "BMP"),
    }
    src = make_hwpx(tmp / "a.hwpx", images=imgs)
    code, result, _, err = run({"inputs": [str(src)]})
    assert code == 0, err
    a, b = entries(src), entries(tmp / "a_용량축소.hwpx")
    with Image.open(io.BytesIO(b["BinData/image1.png"])) as im:
        assert im.mode == "RGBA" and im.size == (600, 400), (im.mode, im.size)
    assert a["BinData/image2.gif"] == b["BinData/image2.gif"]
    with Image.open(io.BytesIO(b["BinData/image3.bmp"])) as im:
        assert im.format == "BMP" and im.size == (600, 450), (im.format, im.size)


@check("파일마다 목표 용량: 이미 목표 이하면 그림을 줄이지 않고 그대로 저장, 달성으로 알림")
def _(tmp):
    src = make_hwpx(tmp / "a.hwpx")
    code, result, _, err = run({"inputs": [str(src)], "target_mode": "each", "target_mb": 500})
    assert code == 0, err
    assert (tmp / "a_용량축소.hwpx").read_bytes() == src.read_bytes()
    assert result["results"][0]["target_reached"] is True
    assert "500MB 이하로" in result["popup"]["message"] and "달성" in result["popup"]["message"]


@check("파일마다 목표 용량: 1단계로 닿으면 멈추고, 못 닿으면 7단계까지 줄여 가장 작은 결과·'미달' 경고")
def _(tmp):
    src = make_hwpx(tmp / "a.hwpx")
    size = src.stat().st_size
    code, result, progress, err = run({"inputs": [str(src)], "target_mode": "each", "target_mb": size / 1048576 / 2})
    assert code == 0, err
    assert result["results"][0]["level"] == 1 and result["results"][0]["target_reached"] is True, result["results"]
    assert not any("2단계" in p for p in progress), progress
    code, result, progress, err = run({"inputs": [str(src)], "target_mode": "each", "target_mb": 0.001})
    assert code == 0, err
    r = result["results"][0]
    assert r["target_reached"] is False and r["level"] == 7, r
    assert any("7단계" in p for p in progress), progress
    assert result["popup"]["level"] == "warning" and "미달" in result["popup"]["message"], result["popup"]
    w, h = size_of(entries(Path(r["output"]))["BinData/image1.jpg"])
    assert (w, h) == (288, 216), (w, h)    # 4×3인치 × 72dpi


@check("목표 용량: 0 이나 글자를 넣으면 알기 쉬운 오류, 비우면 5MB")
def _(tmp):
    src = make_hwpx(tmp / "a.hwpx")
    for mode in ("each", "total"):
        code, _, _, err = run({"inputs": [str(src)], "target_mode": mode, "target_mb": -1})
        assert code == 1 and "0보다 크게" in err, err
        code, _, _, err = run({"inputs": [str(src)], "target_mode": mode, "target_mb": "abc"})
        assert code == 1 and "숫자" in err, err
    code, result, _, err = run({"inputs": [str(src)], "target_mode": "each", "target_mb": ""})
    assert code == 0 and "5MB 이하로" in result["popup"]["message"], (err, result and result["popup"])


@check("전체 합계: 많이 줄어드는 파일부터 줄여 합계를 목표 이하로, 새 폴더에 원래 이름(.hwpx)으로")
def _(tmp):
    big = make_hwpx(tmp / "큰사진.hwpx")
    small = make_hwpx(tmp / "작은.hwpx", images={"BinData/image1.png": img_bytes(noisy((300, 200), seed=13), "PNG")},
                      body=pic("image1", (300, 200), (3, 2)))
    total = big.stat().st_size + small.stat().st_size
    target = (total - big.stat().st_size / 2) / 1048576
    out_dir = tmp / "결과"
    code, result, _, err = run({"inputs": [str(big), str(small)], "target_mode": "total",
                                "target_mb": round(target, 3), "output": str(out_dir)})
    assert code == 0, err
    folder = Path(result["output"])
    assert folder.parent == out_dir and folder.name.startswith(f"한글압축_합계{round(target, 3):g}MB_"), folder
    assert sorted(p.name for p in folder.iterdir()) == ["작은.hwpx", "큰사진.hwpx"]
    assert (folder / "작은.hwpx").read_bytes() == small.read_bytes(), "줄일 필요 없는 파일이 바뀜"
    assert sum(p.stat().st_size for p in folder.iterdir()) <= target * 1048576
    assert result["popup"]["level"] == "success" and "합계" in result["popup"]["message"], result["popup"]
    assert "그대로 저장" in result["popup"]["message"]


@check("전체 합계: 끝까지 줄여도 못 닿으면 가장 작게 줄인 결과를 저장하고 경고")
def _(tmp):
    a = make_hwpx(tmp / "a.hwpx")
    b = make_hwpx(tmp / "b.hwpx", images={"BinData/image1.jpg": img_bytes(noisy((3000, 2000), seed=14), "JPEG", quality=95)})
    code, result, _, err = run({"inputs": [str(a), str(b)], "target_mode": "total", "target_mb": 0.001})
    assert code == 0, err
    assert [r["level"] for r in result["results"]] == [7, 7], result["results"]
    assert result["popup"]["level"] == "warning" and "줄이지 못했습니다" in result["popup"]["title"], result["popup"]
    assert Path(result["output"]).parent == tmp


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
    code, result, _, err = run({"inputs": [str(p) for p in (signed, locked, broken, good)]})
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
    code, result, _, err = run({"inputs": [str(src)]})
    assert code == 0, err
    assert (tmp / "a_용량축소.hwpx").read_bytes() == b"old"
    assert (tmp / "a_용량축소(1).hwpx").exists()
    out_dir = tmp / "결과 폴더"
    code, result, _, err = run({"inputs": [str(src)], "output": str(out_dir)})
    assert code == 0, err
    assert (out_dir / "a_용량축소.hwpx").exists()


@check("옛 한글(hwp): 한글로 hwpx 로 바꾼 뒤 줄여 .hwpx 로 저장, 원본 hwp 는 그대로, 한글은 끔")
def _(tmp):
    F.source_for_hwp = make_hwpx(tmp / "_converted_source.hwpx")
    hwp = tmp / "공문.hwp"
    hwp.write_bytes(b"\xd0\xcf\x11\xe0 fake hwp body")
    before = hwp.read_bytes()
    code, result, progress, err = run({"inputs": [str(hwp)]})
    assert code == 0, err
    out = tmp / "공문_용량축소.hwpx"
    assert out.exists() and out.read_bytes()[:2] == b"PK"
    assert hwp.read_bytes() == before
    assert size_of(entries(out)["BinData/image1.jpg"]) == (600, 450)
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
    code, result, progress, err = run({"inputs": [str(p) for p in files]})
    assert code == 0, err
    assert len(F.hwps) == 1, f"한글을 {len(F.hwps)}번 띄움"
    assert F.hwps[0].visible and F.hwps[0].visible[-1] is True
    assert any(HINT in p for p in progress), progress
    assert len(result["results"]) == 2


@check("옛 한글(hwp) 전체 합계: 한글로 바꿔 합계를 맞추고 한글은 끔")
def _(tmp):
    F.source_for_hwp = make_hwpx(tmp / "_src.hwpx")
    hwp = tmp / "공문.hwp"
    hwp.write_bytes(b"\xd0\xcf\x11\xe0 fake")
    code, result, _, err = run({"inputs": [str(hwp)], "target_mode": "total", "target_mb": 0.2})
    assert code == 0, err
    folder = Path(result["output"])
    assert [p.name for p in folder.iterdir()] == ["공문.hwpx"]
    assert result["results"][0]["converted"] is True
    assert F.hwps[0].quit and F.coinit == F.couninit == 1


@check("옛 한글(hwp)을 한글이 열지 못하면 그 파일만 실패로 알리고 한글은 끔")
def _(tmp):
    F.source_for_hwp = make_hwpx(tmp / "_src.hwpx")
    F.open_ok = False
    hwp = tmp / "x.hwp"
    hwp.write_bytes(b"\xd0\xcf\x11\xe0 fake")
    good = make_hwpx(tmp / "y.hwpx")
    code, result, _, err = run({"inputs": [str(hwp), str(good)]})
    assert code == 0, err
    assert [f["name"] for f in result["failed"]] == ["x.hwp"] and "열지 못했습니다" in result["failed"][0]["error"]
    assert [r["name"] for r in result["results"]] == ["y.hwpx"]
    assert F.hwps[0].quit and F.coinit == F.couninit


@check("중지: 중지 신호가 있으면 저장하지 않고 멈춤(세 방식 모두)")
def _(tmp):
    src = make_hwpx(tmp / "a.hwpx")
    flag = tmp / "stop.flag"
    flag.write_text("1")
    for mode in ("basic", "each", "total"):
        code, result, _, err = run({"inputs": [str(src)], "target_mode": mode, "target_mb": 0.001}, cancel_file=flag)
        assert code == 0, err
        assert result["stopped"] is True and result["popup"]["level"] == "warning", (mode, result)
        assert "중지" in result["popup"]["title"], result["popup"]
    assert not (tmp / "a_용량축소.hwpx").exists()
    assert not list(tmp.glob("*.part"))


@check("줄일 그림이 없으면 그대로 저장하고 그렇게 알림")
def _(tmp):
    src = make_hwpx(tmp / "a.hwpx", images={"BinData/image1.png": img_bytes(noisy((200, 100)), "PNG")},
                    body=pic("image1", (200, 100), (2, 1)))
    code, result, _, err = run({"inputs": [str(src)]})
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
