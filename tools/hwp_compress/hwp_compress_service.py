"""한글 용량 압축 — hwp·hwpx 문서 안의 그림을 줄여 용량을 줄인 새 hwpx 를 만든다.

'기본 줄이기'는 한글의 [그림] → [줄이기] → [용량 줄이기 설정]에서 아래 세 가지를 켜고
[모든 그림에 바로 적용]한 것과 같은 일을 한다.
  1. 잘라낸 그림 영역 지우기      그림을 자른 부분(imgClip 밖)을 실제로 지운다.
  2. 삽입한 그림 크기에 맞춰 줄이기  문서에 보이는 크기(curSz)보다 큰 그림을 그 크기에 맞춘다.
  3. 설정한 해상도로 변경하기      보이는 크기 기준 150dpi 로 맞춘다.
표 칸 배경으로 채운 그림(채우기 '크기에 맞추어')도 그 칸 크기 기준으로 같이 줄인다.

'파일마다 목표 용량 이하'·'전체 합계를 목표 용량 이하'는 같은 방식으로 해상도와 사진 화질을
한 단계씩 낮춰 가며 목표에 맞춘다(LEVELS). 전체 합계 방식은 PDF 용량 압축과 같은 방법으로,
한 단계 더 줄였을 때 가장 많이 줄어드는 파일부터 줄인다.

hwpx 의 그림 단위: imgDim·imgClip 은 그림 픽셀 × 75, curSz·sz·cellSz 는 1/7200 인치(HWPUNIT).
그림을 줄이거나 자르면 그 그림을 쓰는 곳의 imgDim·imgClip 만 새 픽셀에 맞게 고친다. 보이는 크기와
위치(curSz·sz·imgRect 등)는 그대로 두므로 문서 모양은 바뀌지 않는다. 그림 파일 이름·형식도 그대로다.

옛 한글(hwp)은 설치된 한글로 임시 hwpx 를 만든 뒤 줄인다(hcz_hancom). 결과는 hwpx 로 저장한다.
원본은 건드리지 않는다. 전자서명·암호가 있는 문서는 처리하지 않는다. 결과는 다시 열어 확인한다.
구조(검사·결과 확인·이름 규칙)는 'HWPX 용량 줄이기 도우미'(MIT)를 참고했다(NOTICE.md).
"""
from __future__ import annotations

import datetime
import io
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional
from xml.etree import ElementTree

from PIL import Image

from hcz_hancom import HancomConverter, HancomError, is_old_hwp

Progress = Callable[[str], None]
Cancel = Callable[[], bool]

SUPPORTED_EXTS = {".hwp", ".hwpx"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif"}
HWPX_MIMETYPE = "application/hwp+zip"
OUTPUT_SUFFIX = "_용량축소"
HWPUNIT_PER_INCH = 7200
DIM_PER_PIXEL = 75          # imgDim·imgClip = 픽셀 × 75
MAX_ENTRIES = 20000
MAX_EXPANDED_BYTES = 4 * 1024 * 1024 * 1024
MB = 1024 * 1024

# (해상도 dpi, 사진 화질). 1단계가 '기본 줄이기'. 목표 용량 방식은 아래로 내려가며 맞춘다.
LEVELS: list[tuple[int, int]] = [
    (150, 85), (130, 80), (110, 75), (100, 70), (90, 60), (80, 50), (72, 40),
]
BASIC_LEVEL = 1
# 줄일 비율이 이보다 작으면(5% 미만) 다시 저장하지 않는다. 화질만 잃고 용량은 거의 그대로다.
MIN_SCALE_GAIN = 0.95

MODES = ("basic", "each", "total")


class Stopped(Exception):
    """사용자가 중지를 눌렀다."""


# ---------------------------------------------------------------- 확인

def _is_signature_entry(name: str) -> bool:
    n = name.replace("\\", "/").lower()
    return (n.startswith("_xmlsignatures/") or n.startswith("meta-inf/signatures/")
            or "documentsignature" in n or "digitalsignature" in n)


def check_hwpx(path: Path) -> None:
    """줄일 수 있는 hwpx 인지 본다. 아니면 이유를 담은 ValueError."""
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            names = [i.filename.replace("\\", "/") for i in infos]
            lower = {n.lower() for n in names}
            if not infos or len(infos) > MAX_ENTRIES:
                raise ValueError("올바르지 않거나 내부 항목이 너무 많은 한글(hwpx) 파일입니다.")
            if sum(i.file_size for i in infos) > MAX_EXPANDED_BYTES:
                raise ValueError("파일 내부 용량이 너무 커 안전하게 처리할 수 없습니다.")
            if len(set(names)) != len(names):
                raise ValueError("파일 내부에 중복된 항목이 있어 처리할 수 없습니다.")
            if "mimetype" not in lower or "contents/content.hpf" not in lower:
                raise ValueError("올바른 한글(hwpx) 파일이 아닙니다.")
            if any(_is_signature_entry(n) for n in names):
                raise ValueError("전자서명 또는 문서 보호 정보가 있어 용량을 줄일 수 없습니다.")
            mime_name = next(n for n in names if n.lower() == "mimetype")
            if z.read(mime_name).decode("utf-8", "replace").strip().lower() != HWPX_MIMETYPE:
                raise ValueError("지원하지 않는 형식의 한글(hwpx) 파일입니다.")
            for n in names:
                if n.lower() == "meta-inf/manifest.xml" and b"encryption-data" in z.read(n):
                    raise ValueError("암호가 걸린 한글 문서는 용량을 줄일 수 없습니다.")
    except zipfile.BadZipFile as exc:
        raise ValueError("손상되었거나 보호된 한글(hwpx) 문서입니다.") from exc


# ---------------------------------------------------------------- 문서에서 그림 쓰임 찾기

_ATTR_RE = r'{name}="(-?\d+)"'


def _attrs(tag: str, *names: str) -> Optional[tuple[int, ...]]:
    out = []
    for n in names:
        m = re.search(_ATTR_RE.format(name=n), tag)
        if not m:
            return None
        out.append(int(m.group(1)))
    return tuple(out)


@dataclass
class PicUse:
    """그림 개체(hp:pic) 하나. 위치는 XML 글자 위치(그 파트 안)."""
    part: str
    clip_span: tuple[int, int]
    dim_span: tuple[int, int]
    clip: tuple[int, int, int, int]   # left, right, top, bottom (픽셀×75)
    dim: tuple[int, int]              # width, height (픽셀×75)
    show: tuple[int, int]             # 보이는 크기(HWPUNIT). 모르면 (0, 0)


@dataclass
class ImageUse:
    href: str
    pics: list[PicUse] = field(default_factory=list)
    fills: list[tuple[int, int]] = field(default_factory=list)   # 배경으로 채운 칸 크기(HWPUNIT)
    blocked: str = ""   # 비어 있지 않으면 줄이지 않는 이유


@dataclass
class DocPlan:
    images: dict[str, ImageUse]       # href(BinData/…) → 쓰임
    xml_parts: dict[str, str]         # 고칠 수 있는 XML 파트 원문


def _manifest_items(hpf: str) -> dict[str, str]:
    items = {}
    for tag in re.findall(r"<(?:\w+:)?item\b[^>]*>", hpf):
        i = re.search(r'\bid="([^"]+)"', tag)
        h = re.search(r'\bhref="([^"]+)"', tag)
        if i and h:
            items[i.group(1)] = h.group(1)
    return items


def _cell_sizes_by_border_fill(xml: str) -> tuple[dict[str, list[tuple[int, int]]], set[str]]:
    """표 칸(tc)의 borderFillIDRef → 그 칸 크기들. tc 가 아닌 곳에서 쓰인 borderFill 은 따로 모은다."""
    sizes: dict[str, list[tuple[int, int]]] = {}
    other: set[str] = set()
    stack: list[Optional[str]] = []
    for m in re.finditer(r"<(/?)(\w+:)?(\w+)\b([^>]*?)(/?)>", xml):
        closing, local, attrs, selfclose = m.group(1), m.group(3), m.group(4), m.group(5)
        ref = re.search(r'\bborderFillIDRef="([^"]+)"', attrs)
        if local == "tc":
            if closing:
                if stack:
                    stack.pop()
            elif not selfclose:
                stack.append(ref.group(1) if ref else None)
            continue
        if ref and not closing:
            other.add(ref.group(1))
        if local == "cellSz" and stack and stack[-1] is not None:
            wh = _attrs(attrs, "width", "height")
            if wh:
                sizes.setdefault(stack[-1], []).append(wh)
    return sizes, other


def analyze(z: zipfile.ZipFile) -> DocPlan:
    """그림마다 어디에, 얼마나 크게 보이는지 모은다. 알 수 없는 곳에 쓰인 그림은 막는다(blocked)."""
    names = z.namelist()
    hpf_name = next(n for n in names if n.lower() == "contents/content.hpf")
    items = _manifest_items(z.read(hpf_name).decode("utf-8", "replace"))
    images: dict[str, ImageUse] = {}
    for item_id, href in items.items():
        if href.lower().startswith("bindata/") and Path(href).suffix.lower() in IMAGE_EXTS and href in names:
            images[item_id] = ImageUse(href)

    parts = {n: z.read(n).decode("utf-8") for n in names
             if n.startswith("Contents/") and n.endswith(".xml")}
    ref_count: dict[str, int] = {}
    seen_count: dict[str, int] = {}
    for xml in parts.values():
        for r in re.findall(r'binaryItemIDRef="([^"]+)"', xml):
            ref_count[r] = ref_count.get(r, 0) + 1

    # 1) 그림 개체(hp:pic)
    for part, xml in parts.items():
        for m in re.finditer(r"<(\w+:)?pic\b[^>]*(?<!/)>.*?</\1?pic>", xml, re.S):
            block, base = m.group(0), m.start()
            # 그림 개체의 그림: 채우기(fillBrush) 안의 그림이 아닌 hc:img (위치는 한글 버전마다 다르다).
            body = re.sub(r"<(\w+:)?fillBrush\b.*?</\1?fillBrush>", "", block, flags=re.S)
            img = re.search(r'<(?:\w+:)?img\b[^>]*binaryItemIDRef="([^"]+)"', body)
            if not img:
                continue
            ref = img.group(1)
            seen_count[ref] = seen_count.get(ref, 0) + 1
            use = images.get(ref)
            if use is None:
                continue
            clip_m = re.search(r"<(?:\w+:)?imgClip\b[^>]*/>", block)
            dim_m = re.search(r"<(?:\w+:)?imgDim\b[^>]*/>", block)
            clip = _attrs(clip_m.group(0), "left", "right", "top", "bottom") if clip_m else None
            dim = _attrs(dim_m.group(0), "dimwidth", "dimheight") if dim_m else None
            if not clip or not dim or dim[0] <= 0 or dim[1] <= 0:
                use.blocked = "그림 자르기 정보를 읽지 못함"
                continue
            show = (0, 0)
            for tag in ("curSz", "sz"):
                t = re.search(rf"<(?:\w+:)?{tag}\b[^>]*/>", block)
                wh = _attrs(t.group(0), "width", "height") if t else None
                if wh and wh[0] > 0 and wh[1] > 0:
                    show = wh
                    break
            use.pics.append(PicUse(part, (base + clip_m.start(), base + clip_m.end()),
                                   (base + dim_m.start(), base + dim_m.end()), clip, dim, show))

    # 2) 표 칸 배경 그림(채우기 '크기에 맞추어' = imgBrush mode="TOTAL")
    cell_sizes: dict[str, list[tuple[int, int]]] = {}
    other_bf: set[str] = set()
    for xml in parts.values():
        sizes, other = _cell_sizes_by_border_fill(xml)
        for k, v in sizes.items():
            cell_sizes.setdefault(k, []).extend(v)
        other_bf |= other
    for xml in parts.values():
        # 내용이 없는(<… />) borderFill 은 건너뛴다. 아니면 다음 borderFill 의 내용까지 붙잡는다.
        for m in re.finditer(r"<(\w+:)?borderFill\b([^>]*)(?<!/)>(.*?)</\1?borderFill>", xml, re.S):
            id_m = re.search(r'\bid="([^"]+)"', m.group(2))
            if not id_m:
                continue
            bf_id, body = id_m.group(1), m.group(3)
            for b in re.finditer(r"<(?:\w+:)?imgBrush\b([^>]*)>(.*?)</(?:\w+:)?imgBrush>", body, re.S):
                r = re.search(r'binaryItemIDRef="([^"]+)"', b.group(2))
                if not r:
                    continue
                ref = r.group(1)
                seen_count[ref] = seen_count.get(ref, 0) + 1
                use = images.get(ref)
                if use is None:
                    continue
                mode = re.search(r'\bmode="([^"]+)"', b.group(1))
                if not mode or mode.group(1) != "TOTAL":
                    use.blocked = "바둑판식 등 크기에 맞추지 않는 채우기 그림"
                elif bf_id in other_bf or bf_id not in cell_sizes:
                    use.blocked = "표 칸이 아닌 곳의 채우기 그림"
                else:
                    use.fills.extend(cell_sizes[bf_id])

    for ref, use in images.items():
        if ref_count.get(ref, 0) != seen_count.get(ref, 0) and not use.blocked:
            use.blocked = "그림을 쓰는 곳을 모두 알 수 없음"
        if not use.pics and not use.fills and not use.blocked:
            use.blocked = "문서에서 쓰이는 곳이 없음"
    return DocPlan({u.href: u for u in images.values()}, parts)


# ---------------------------------------------------------------- 그림 하나 줄이기

@dataclass
class ImageChange:
    href: str
    data: bytes
    crop_px: tuple[int, int, int, int]   # 원본 픽셀 기준 left, top, right, bottom
    new_size: tuple[int, int]
    old_size: tuple[int, int]


def _scale_needed(use: ImageUse, px: tuple[int, int], dpi: int) -> float:
    """보이는 크기를 dpi 로 나타내는 데 필요한 배율(1 이면 줄이지 않음)."""
    w, h = px
    need = 0.0
    known = False
    for pic in use.pics:
        fx, fy = w / pic.dim[0], h / pic.dim[1]
        cw = max(1.0, (pic.clip[1] - pic.clip[0]) * fx)
        ch = max(1.0, (pic.clip[3] - pic.clip[2]) * fy)
        if pic.show[0] <= 0 or pic.show[1] <= 0:
            return 1.0   # 보이는 크기를 모르면 줄이지 않는다
        known = True
        need = max(need, pic.show[0] / HWPUNIT_PER_INCH * dpi / cw, pic.show[1] / HWPUNIT_PER_INCH * dpi / ch)
    for cw_unit, ch_unit in use.fills:
        if cw_unit <= 0 or ch_unit <= 0:
            return 1.0
        known = True
        need = max(need, cw_unit / HWPUNIT_PER_INCH * dpi / w, ch_unit / HWPUNIT_PER_INCH * dpi / h)
    return min(1.0, need) if known else 1.0


def _crop_box(use: ImageUse, px: tuple[int, int]) -> tuple[int, int, int, int]:
    """잘라낸 곳을 지울 범위(픽셀). 여러 곳에서 다르게 잘라 쓰면 모두를 담는 범위. 배경 그림은 자르지 않는다."""
    w, h = px
    if use.fills or not use.pics:
        return (0, 0, w, h)
    # 정수로만 계산한다(소수 오차로 한 픽셀 더 남기지 않게). 왼쪽·위는 내림, 오른쪽·아래는 올림.
    left, top = w, h
    right = bottom = 0
    for pic in use.pics:
        left = min(left, pic.clip[0] * w // pic.dim[0])
        right = max(right, -(-pic.clip[1] * w // pic.dim[0]))
        top = min(top, pic.clip[2] * h // pic.dim[1])
        bottom = max(bottom, -(-pic.clip[3] * h // pic.dim[1]))
    box = (max(0, left), max(0, top), min(w, right), min(h, bottom))
    if box[2] - box[0] < 1 or box[3] - box[1] < 1:
        return (0, 0, w, h)
    return box


def _encode(img: Image.Image, ext: str, quality: int, info: dict, dpi_scale: float) -> bytes:
    out = io.BytesIO()
    extra = {}
    dpi = info.get("dpi")
    if dpi and dpi[0] and dpi[1]:
        extra["dpi"] = (round(dpi[0] * dpi_scale, 3), round(dpi[1] * dpi_scale, 3))
    if ext in (".jpg", ".jpeg"):
        if img.mode not in ("RGB", "L", "CMYK"):
            img = img.convert("RGB")
        if info.get("icc_profile"):
            extra["icc_profile"] = info["icc_profile"]
        if info.get("exif"):
            extra["exif"] = info["exif"]
        img.save(out, "JPEG", quality=int(quality), optimize=True, **extra)
    elif ext == ".png":
        if info.get("icc_profile"):
            extra["icc_profile"] = info["icc_profile"]
        img.save(out, "PNG", optimize=True, **extra)
    elif ext == ".bmp":
        if img.mode not in ("RGB", "L", "1", "RGBA"):
            img = img.convert("RGB")
        img.save(out, "BMP", **extra)
    elif ext == ".gif":
        if img.mode != "P":
            img = img.convert("RGB").quantize(colors=256)
        img.save(out, "GIF")
    else:
        raise ValueError("지원하지 않는 그림 형식")
    return out.getvalue()


def shrink_image(data: bytes, use: ImageUse, dpi: int, quality: int) -> Optional[ImageChange]:
    """그림 하나를 잘라내고 줄인다. 이득이 없으면 None."""
    ext = Path(use.href).suffix.lower()
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        return None
    if ext == ".gif" and getattr(img, "is_animated", False):
        return None
    w, h = img.size
    # 문서에 적힌 그림 크기(imgDim)의 가로세로 비율이 실제 그림과 다르면(회전 정보 등) 좌표를 믿을 수 없어 두지 않는다.
    for pic in use.pics:
        if abs(pic.dim[0] * h - pic.dim[1] * w) > 0.02 * pic.dim[0] * h:
            return None
    box = _crop_box(use, (w, h))
    cropped = box != (0, 0, w, h)
    scale = _scale_needed(use, (w, h), dpi)
    if not cropped and scale >= MIN_SCALE_GAIN:
        return None
    cw, ch = box[2] - box[0], box[3] - box[1]
    nw, nh = max(1, round(cw * scale)), max(1, round(ch * scale))
    info = dict(img.info)
    work = img
    if work.mode == "P":
        work = work.convert("RGBA" if "transparency" in work.info else "RGB")
    elif work.mode in ("LA", "PA"):
        work = work.convert("RGBA")
    elif work.mode in ("I;16", "I", "F"):
        work = work.convert("RGB")
    if cropped:
        work = work.crop(box)
    if (nw, nh) != work.size:
        work = work.resize((nw, nh), Image.LANCZOS)
    if ext == ".gif" and img.mode == "P" and work.mode != "P":
        work = work.convert("RGB")
    try:
        new = _encode(work, ext, quality, info, nw / cw if cw else 1.0)
    except Exception:
        return None
    if len(new) >= len(data):
        return None
    return ImageChange(use.href, new, box, (nw, nh), (w, h))


# ---------------------------------------------------------------- 문서 만들기

def _rewrite_xml(plan: DocPlan, changes: dict[str, ImageChange]) -> dict[str, str]:
    """줄인 그림을 쓰는 hp:pic 의 imgDim·imgClip 을 새 픽셀에 맞게 고친다."""
    edits: dict[str, list[tuple[int, int, str]]] = {}
    for href, ch in changes.items():
        use = plan.images[href]
        ow, oh = ch.old_size
        nw, nh = ch.new_size
        left, top, right, bottom = ch.crop_px
        new_dim = (nw * DIM_PER_PIXEL, nh * DIM_PER_PIXEL)
        for pic in use.pics:
            fx, fy = ow / pic.dim[0], oh / pic.dim[1]      # 이 그림의 dim 단위 → 원본 픽셀
            sx, sy = nw / (right - left), nh / (bottom - top)  # 원본 픽셀(자른 뒤) → 새 픽셀

            def to_new(v: int, f: float, start: int, s: float, limit: int) -> int:
                return max(0, min(limit, round((v * f - start) * s * DIM_PER_PIXEL)))

            cl = to_new(pic.clip[0], fx, left, sx, new_dim[0])
            cr = to_new(pic.clip[1], fx, left, sx, new_dim[0])
            ct = to_new(pic.clip[2], fy, top, sy, new_dim[1])
            cb = to_new(pic.clip[3], fy, top, sy, new_dim[1])
            xml = plan.xml_parts[pic.part]
            clip_tag = xml[pic.clip_span[0]:pic.clip_span[1]]
            dim_tag = xml[pic.dim_span[0]:pic.dim_span[1]]
            for name, val in (("left", cl), ("right", cr), ("top", ct), ("bottom", cb)):
                clip_tag = re.sub(rf'\b{name}="-?\d+"', f'{name}="{val}"', clip_tag, count=1)
            dim_tag = re.sub(r'\bdimwidth="\d+"', f'dimwidth="{new_dim[0]}"', dim_tag, count=1)
            dim_tag = re.sub(r'\bdimheight="\d+"', f'dimheight="{new_dim[1]}"', dim_tag, count=1)
            edits.setdefault(pic.part, []).append((*pic.clip_span, clip_tag))
            edits.setdefault(pic.part, []).append((*pic.dim_span, dim_tag))
    out = {}
    for part, ops in edits.items():
        xml = plan.xml_parts[part]
        for start, end, text in sorted(set(ops), reverse=True):
            xml = xml[:start] + text + xml[end:]
        out[part] = xml
    return out


@dataclass
class LevelResult:
    path: Path
    size: int
    images_total: int
    images_reduced: int


def build_level(src: Path, out: Path, level: int, cancel: Optional[Cancel] = None,
                progress: Optional[Progress] = None, label: str = "") -> LevelResult:
    """src(hwpx)를 level 단계로 줄여 out 에 쓴다."""
    dpi, quality = LEVELS[level - 1]
    with zipfile.ZipFile(src) as zin:
        plan = analyze(zin)
        candidates = [u for u in plan.images.values() if not u.blocked]
        changes: dict[str, ImageChange] = {}
        for n, use in enumerate(candidates, start=1):
            if cancel and cancel():
                raise Stopped()
            ch = shrink_image(zin.read(use.href), use, dpi, quality)
            if ch is not None:
                changes[use.href] = ch
            if progress and (n == len(candidates) or n % 10 == 0):
                progress(f"{label}그림 {n}/{len(candidates)}개 확인")
        new_xml = _rewrite_xml(plan, changes)
        infos = zin.infolist()
        infos.sort(key=lambda i: 0 if i.filename.lower() == "mimetype" else 1)
        with zipfile.ZipFile(out, "w", allowZip64=True) as zout:
            for info in infos:
                if cancel and cancel():
                    raise Stopped()
                if info.filename in changes:
                    data = changes[info.filename].data
                elif info.filename in new_xml:
                    data = new_xml[info.filename].encode("utf-8")
                else:
                    data = zin.read(info.filename)
                zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
                zi.external_attr = info.external_attr
                zi.compress_type = zipfile.ZIP_STORED if info.filename.lower() == "mimetype" else (
                    info.compress_type if info.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                    else zipfile.ZIP_DEFLATED)
                zout.writestr(zi, data)
    validate_output(out, src, set(new_xml))
    return LevelResult(out, out.stat().st_size, len(plan.images), len(changes))


def validate_output(out: Path, original: Path, changed_xml: set[str] = frozenset()) -> None:
    """결과 hwpx 를 다시 열어 원본 항목이 모두 있고, 고친 XML 이 올바르고, 그림이 열리는지 본다."""
    try:
        with zipfile.ZipFile(original) as zo:
            want = {i.filename for i in zo.infolist() if not i.filename.endswith("/")}
        with zipfile.ZipFile(out) as z:
            if z.testzip() is not None:
                raise ValueError("결과 파일이 손상되었습니다.")
            names = z.namelist()
            missing = sorted(want - set(names))
            if missing:
                raise ValueError(f"결과 파일을 만드는 중 일부 문서 내용이 빠졌습니다. (항목: {missing[0]})")
            if not names or names[0].lower() != "mimetype":
                raise ValueError("결과 파일의 형식 정보(mimetype)가 맨 앞에 있지 않습니다.")
            for n in changed_xml:
                ElementTree.fromstring(z.read(n))
            for n in names:
                if n.lower().startswith("bindata/") and Path(n).suffix.lower() in IMAGE_EXTS:
                    with Image.open(io.BytesIO(z.read(n))) as img:
                        img.load()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("완성된 한글(hwpx) 파일을 확인하지 못했습니다.") from exc


# ---------------------------------------------------------------- 파일 준비·이름

def unique(path: Path) -> Path:
    if not path.exists():
        return path
    for n in range(1, 10000):
        cand = path.with_name(f"{path.stem}({n}){path.suffix}")
        if not cand.exists():
            return cand
    raise RuntimeError(f"저장할 이름을 정하지 못했습니다: {path.name}")


def output_path_for(src: Path, folder: Optional[Path]) -> Path:
    return unique((folder or src.parent) / f"{src.stem}{OUTPUT_SUFFIX}.hwpx")


def _prepare(path: Path, work: Path, converter: Optional[HancomConverter], say: Progress) -> tuple[Path, bool]:
    """줄일 hwpx 를 준비한다. 옛 한글이면 한글로 바꾼 임시 hwpx."""
    if is_old_hwp(path):
        if converter is None:
            raise HancomError("옛 한글(hwp) 파일을 바꿀 준비가 되지 않았습니다.")
        say(f"{path.name}: 한글로 hwpx 로 바꾸는 중")
        dst = work / "converted.hwpx"
        converter.convert(path, dst)
        check_hwpx(dst)
        return dst, True
    check_hwpx(path)
    return path, False


def _save(chosen: Path, out: Path) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_name(out.name + ".part")
    try:
        shutil.copyfile(chosen, part)
        part.replace(out)
    finally:
        try:
            part.unlink()
        except OSError:
            pass
    return out.stat().st_size


def friendly_error(exc: BaseException) -> str:
    if isinstance(exc, PermissionError):
        return "파일을 읽거나 저장할 수 없습니다. 한글에서 파일을 닫았는지, 저장 폴더에 쓸 수 있는지 확인해 주세요."
    if isinstance(exc, (ValueError, HancomError, FileNotFoundError)):
        return str(exc).strip() or type(exc).__name__
    if isinstance(exc, OSError):
        return "파일을 읽거나 저장할 수 없습니다. 파일이 손상되지 않았는지, 저장 폴더에 쓸 수 있는지 확인해 주세요."
    return "문서를 처리하는 중 오류가 발생했습니다. 원본 파일은 바뀌지 않았습니다."


# ---------------------------------------------------------------- 기본 줄이기 · 파일마다 목표

def compress_file(path: Path, mode: str, target_bytes: int = 0, output_dir: Optional[Path] = None,
                  converter: Optional[HancomConverter] = None,
                  progress: Optional[Progress] = None, cancel: Optional[Cancel] = None) -> dict:
    say = progress or (lambda _t: None)
    path = Path(path)
    original = path.stat().st_size
    work = Path(tempfile.mkdtemp(prefix="jbedu_hcz_"))
    try:
        src, converted = _prepare(path, work, converter, say)
        source_size = src.stat().st_size
        chosen, level, best, note = src, 0, None, ""
        if mode == "each" and source_size <= target_bytes:
            note = "이미 목표 용량 이하라 그림을 줄이지 않았습니다."
        else:
            last = BASIC_LEVEL if mode == "basic" else len(LEVELS)
            for lv in range(BASIC_LEVEL, last + 1):
                if cancel and cancel():
                    raise Stopped()
                label = f"{path.name}: " + (f"{lv}단계 " if mode != "basic" else "")
                res = build_level(src, work / f"level_{lv}.hwpx", lv, cancel, say, label)
                if best is None or res.size < best.size:
                    best, level = res, lv
                if mode == "each" and res.size <= target_bytes:
                    break
            if best is not None and best.size < source_size:
                chosen = best.path
            else:
                level = 0
                note = "줄일 수 있는 그림이 없어 그림은 그대로 두었습니다."
        out = output_path_for(path, output_dir)
        size = _save(chosen, out)
        return {
            "name": path.name,
            "output": str(out),
            "original_bytes": original,
            "output_bytes": size,
            "converted": converted,
            "images_total": best.images_total if best else 0,
            "images_reduced": best.images_reduced if (best and level) else 0,
            "level": level,
            "target_reached": (size <= target_bytes) if mode == "each" else None,
            "note": note,
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)


def compress_files(paths: list[Path], mode: str, target_mb: float = 0, output_dir: Optional[Path] = None,
                   progress: Optional[Progress] = None, cancel: Optional[Cancel] = None) -> dict:
    """여러 파일을 차례로 줄인다(기본 줄이기·파일마다 목표). 한 파일이 실패해도 나머지는 계속한다."""
    if mode not in MODES:
        raise ValueError(f"알 수 없는 방식입니다: {mode}")
    if mode == "total":
        return compress_group_to_total(paths, target_mb, output_dir, progress, cancel)
    if mode == "each" and target_mb <= 0:
        raise ValueError("'목표 용량(MB)'은 0보다 크게 입력하세요.")
    say = progress or (lambda _t: None)
    target_bytes = int(target_mb * MB) if mode == "each" else 0
    results: list[dict] = []
    failed: list[dict] = []
    stopped = False
    converter = HancomConverter(progress=say) if any(is_old_hwp(Path(p)) for p in paths) else None
    try:
        for index, p in enumerate(paths, start=1):
            if cancel and cancel():
                stopped = True
                break
            p = Path(p)
            if len(paths) > 1:
                say(f"[{index}/{len(paths)}] {p.name}")
            try:
                results.append(compress_file(p, mode, target_bytes, output_dir, converter, say, cancel))
            except Stopped:
                stopped = True
                break
            except Exception as exc:
                reason = friendly_error(exc)
                failed.append({"name": p.name, "error": reason})
                say(f"{p.name}: 줄이지 못했습니다 ({reason})")
    finally:
        if converter is not None:
            converter.close()
    skipped = max(0, len(paths) - len(results) - len(failed)) if stopped else 0
    return {"mode": mode, "results": results, "failed": failed, "stopped": stopped, "skipped": skipped,
            "target_mb": target_mb if mode == "each" else 0, "folder": None}


# ---------------------------------------------------------------- 전체 합계를 목표 용량 이하

def compress_group_to_total(paths: list[Path], target_mb: float, output_dir: Optional[Path] = None,
                            progress: Optional[Progress] = None, cancel: Optional[Cancel] = None) -> dict:
    """여러 파일의 합계가 목표 이하가 되도록 파일마다 단계를 고른다(PDF 용량 압축의 합계 방식과 같은 방법).
    모두 원본(0단계)에서 시작해, 합계가 목표를 넘는 동안 '한 단계 더 줄였을 때 가장 많이 줄어드는 파일'만
    한 단계 올린다. 결과는 새 폴더에 원래 이름(.hwpx)으로 저장한다."""
    if target_mb <= 0:
        raise ValueError("'목표 용량(MB)'은 0보다 크게 입력하세요.")
    say = progress or (lambda _t: None)
    target_bytes = int(target_mb * MB)
    work = Path(tempfile.mkdtemp(prefix="jbedu_hczg_"))
    failed: list[dict] = []
    states: list[dict] = []
    stopped = False
    converter = HancomConverter(progress=say) if any(is_old_hwp(Path(p)) for p in paths) else None
    try:
        for index, p in enumerate(paths):
            p = Path(p)
            if cancel and cancel():
                stopped = True
                break
            sub = work / f"f{index:03d}"
            sub.mkdir()
            try:
                src, converted = _prepare(p, sub, converter, say)
            except Exception as exc:
                failed.append({"name": p.name, "error": friendly_error(exc)})
                continue
            states.append({"path": p, "src": src, "converted": converted, "dir": sub,
                           "original": p.stat().st_size, "sizes": {0: src.stat().st_size},
                           "files": {0: src}, "level": 0, "done": False, "images": (0, 0)})
        if converter is not None:
            converter.close()
            converter = None

        def measure(state: dict, level: int) -> int:
            if level not in state["sizes"]:
                if cancel and cancel():
                    raise Stopped()
                res = build_level(state["src"], state["dir"] / f"level_{level}.hwpx", level, cancel,
                                  say, f"{state['path'].name}: {level}단계 ")
                state["sizes"][level] = res.size
                state["files"][level] = res.path
                state.setdefault("imgs", {})[level] = (res.images_total, res.images_reduced)
            return state["sizes"][level]

        def next_step(state: dict):
            current = state["sizes"][state["level"]]
            for level in range(state["level"] + 1, min(state["level"] + 3, len(LEVELS) + 1)):
                size = measure(state, level)
                if size < current * 0.995:
                    return level, current - size
            return None

        total = sum(s["sizes"][0] for s in states)
        if states:
            say(f"한글 파일 {len(states)}개, 합계 {total / MB:.2f}MB → 목표 {target_mb:g}MB")
        try:
            while total > target_bytes and not stopped:
                if cancel and cancel():
                    raise Stopped()
                best = None
                for state in states:
                    if state["done"]:
                        continue
                    try:
                        step = next_step(state)
                    except Stopped:
                        raise
                    except Exception as exc:   # 이 파일은 줄이지 않고 그대로 둔다
                        state["done"] = True
                        say(f"{state['path'].name}: 줄이지 못해 그대로 둡니다 ({friendly_error(exc)})")
                        continue
                    if step is None:
                        state["done"] = True
                        continue
                    if best is None or step[1] > best[2]:
                        best = (state, step[0], step[1])
                if best is None:
                    break
                state, level, saving = best
                state["level"] = level
                total -= saving
                say(f"{state['path'].name}: {level}단계로 줄임 → 합계 {total / MB:.2f}MB")
        except Stopped:
            stopped = True
            say("중지 요청으로 멈췄습니다. 지금까지 줄인 결과로 저장합니다.")

        results = []
        folder = None
        if states:
            stamp = datetime.datetime.now().strftime("%m%d_%H%M")
            root = output_dir or states[0]["path"].parent
            folder = root / f"한글압축_합계{target_mb:g}MB_{stamp}"
            n = 1
            while folder.exists():
                folder = root / f"한글압축_합계{target_mb:g}MB_{stamp}({n})"
                n += 1
            folder.mkdir(parents=True)
            for state in states:
                out = unique(folder / f"{state['path'].stem}.hwpx")
                size = _save(state["files"][state["level"]], out)
                total_imgs, reduced = state.get("imgs", {}).get(state["level"], (0, 0))
                results.append({
                    "name": state["path"].name, "output": str(out), "original_bytes": state["original"],
                    "output_bytes": size, "converted": state["converted"], "level": state["level"],
                    "images_total": total_imgs, "images_reduced": reduced, "target_reached": None,
                    "note": "" if state["level"] else "그대로 저장",
                })
        final_total = sum(r["output_bytes"] for r in results)
        skipped = max(0, len(paths) - len(states) - len(failed))
        return {"mode": "total", "results": results, "failed": failed, "stopped": stopped, "skipped": skipped,
                "target_mb": target_mb, "folder": str(folder) if folder else None,
                "original_total": sum(s["original"] for s in states), "final_total": final_total,
                "achieved": bool(results) and final_total <= target_bytes}
    finally:
        if converter is not None:
            converter.close()
        shutil.rmtree(work, ignore_errors=True)
