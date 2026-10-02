"""한글 용량 압축 — hwp·hwpx 문서 안의 큰 그림을 줄여 용량을 줄인 새 hwpx 를 만든다.

참고: 'HWPX 용량 줄이기 도우미 v1.0'(gitlab.aigov.go.kr/kimosed/hwpx-size-reduction-assistant, MIT)의
처리 규칙을 파이썬으로 옮겼다. 압축 방식별 기준값, 그림을 고르는 규칙, 목표 용량 단계는 원본과 같다.

- hwpx 는 ZIP 이다. BinData 안의 그림(jpg·jpeg·png·bmp·gif)만 줄이고, 본문 XML·다른 항목은 그대로 둔다.
  그림 파일 이름·형식을 바꾸지 않으므로 문서 안의 참조도 바뀌지 않는다.
- 옛 한글(hwp)은 설치된 한글로 임시 hwpx 를 만든 뒤 줄인다(hcz_hancom). 결과는 hwpx 로 저장한다.
- 원본은 건드리지 않는다. 결과는 '원본이름_용량축소.hwpx'(같은 이름이 있으면 (1), (2) …).
- 전자서명·암호가 있는 문서는 건드리지 않는다. 줄인 결과가 더 크면 줄이기 전 문서를 그대로 쓴다.
- 결과 파일을 다시 열어 빠진 항목이 없는지, 그림이 열리는지 확인한 뒤에만 저장한다.
"""
from __future__ import annotations

import io
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from PIL import Image, ImageOps

from hcz_hancom import HancomConverter, HancomError, is_old_hwp

Progress = Callable[[str], None]
Cancel = Callable[[], bool]

SUPPORTED_EXTS = {".hwp", ".hwpx"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif"}
HWPX_MIMETYPE = "application/hwp+zip"
OUTPUT_SUFFIX = "_용량축소"

# 원본 프로그램과 같은 기준: 크기·용량이 모두 작은 그림은 그대로 둔다.
MIN_FILE_BYTES = 300 * 1024
MIN_LONG_EDGE = 1600
MAX_ENTRIES = 20000
MAX_EXPANDED_BYTES = 4 * 1024 * 1024 * 1024
MB = 1024 * 1024


@dataclass(frozen=True)
class Preset:
    key: str
    name: str
    max_long_edge: int
    jpeg_quality: int
    target_mb: float = 0.0   # 0 이면 목표 용량 없음


PRESETS = {
    "quality": Preset("quality", "화질 우선", 2560, 90),
    "standard": Preset("standard", "용량 우선", 1600, 78),
    "mail": Preset("mail", "메일 첨부용(10MB)", 1920, 85, 10.0),
    "target": Preset("target", "목표 용량", 1920, 85),
}

# 목표 용량이 있는 방식은 이 단계를 차례로 시도하고, 목표에 닿으면 멈춘다.
TARGET_STEPS = [(1920, 85), (1600, 80), (1440, 75), (1280, 70)]


class Stopped(Exception):
    """사용자가 중지를 눌렀다."""


def make_preset(mode: str, target_mb: float | None = None) -> Preset:
    preset = PRESETS.get(mode)
    if preset is None:
        raise ValueError(f"알 수 없는 압축 방식입니다: {mode}")
    if preset.key == "target":
        if target_mb is None or target_mb <= 0:
            raise ValueError("'목표 용량(MB)'은 0보다 크게 입력하세요.")
        preset = Preset(preset.key, preset.name, preset.max_long_edge, preset.jpeg_quality, float(target_mb))
    return preset


def attempts_for(preset: Preset) -> list[tuple[int, int]]:
    if preset.target_mb > 0:
        return list(TARGET_STEPS)
    return [(preset.max_long_edge, preset.jpeg_quality)]


# ---------------------------------------------------------------- 확인

def _is_signature_entry(name: str) -> bool:
    n = name.replace("\\", "/").lower()
    return (n.startswith("_xmlsignatures/") or n.startswith("meta-inf/signatures/")
            or "documentsignature" in n or "digitalsignature" in n)


def is_image_resource(name: str) -> bool:
    n = name.replace("\\", "/")
    in_bindata = n.lower().startswith("bindata/") or "/bindata/" in n.lower()
    return in_bindata and Path(n).suffix.lower() in IMAGE_EXTS


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


# ---------------------------------------------------------------- 그림 줄이기

@dataclass
class ImageResult:
    name: str
    original_bytes: int
    output_bytes: int
    reduced: bool
    reason: str = ""


def _has_alpha(img: Image.Image) -> bool:
    if img.mode in ("RGBA", "LA", "PA"):
        return True
    if img.mode == "P" and "transparency" in img.info:
        return True
    return False


def optimize_image(data: bytes, name: str, max_long_edge: int, jpeg_quality: int,
                   skip_small: bool = True) -> tuple[Optional[bytes], str]:
    """그림 하나를 줄인다. 줄인 바이트(또는 그대로 둘 때 None)와 그대로 둔 이유를 돌려준다.
    원본 프로그램(ImageOptimizer.cs)과 같은 규칙이다."""
    ext = Path(name).suffix.lower()
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        return None, "처리 실패: 그림을 읽을 수 없습니다."
    try:
        w, h = img.size
        if ext == ".gif" and getattr(img, "is_animated", False):
            return None, "움직이는 GIF이므로 원본 유지"
        long_edge = max(w, h)
        if skip_small and len(data) < MIN_FILE_BYTES and long_edge < MIN_LONG_EDGE:
            return None, "크기와 용량이 모두 작음"
        jpeg = ext in (".jpg", ".jpeg")
        if not jpeg and long_edge <= max_long_edge:
            return None, "기준 크기 이하인 PNG 그림이므로 원본 유지" if ext == ".png" else "이미 기준 크기 이하"

        icc = img.info.get("icc_profile")
        dpi = img.info.get("dpi")
        try:
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass
        ow, oh = img.size
        long_edge = max(ow, oh)
        scale = max_long_edge / long_edge if long_edge > max_long_edge else 1.0
        nw, nh = max(1, round(ow * scale)), max(1, round(oh * scale))

        alpha = ext == ".png" and _has_alpha(img)
        if alpha:
            img = img.convert("RGBA")
        else:
            # 투명한 부분은 흰 바탕으로 채운다(원본 프로그램과 같음).
            if _has_alpha(img):
                rgba = img.convert("RGBA")
                bg = Image.new("RGB", rgba.size, (255, 255, 255))
                bg.paste(rgba, mask=rgba.split()[-1])
                img = bg
            else:
                img = img.convert("RGB")
        if (nw, nh) != img.size:
            img = img.resize((nw, nh), Image.LANCZOS)

        out = io.BytesIO()
        extra = {}
        if dpi:
            extra["dpi"] = dpi
        if jpeg:
            if icc:
                extra["icc_profile"] = icc
            img.save(out, "JPEG", quality=int(jpeg_quality), optimize=True, **extra)
        elif ext == ".png":
            if icc:
                extra["icc_profile"] = icc
            img.save(out, "PNG", optimize=True, **extra)
        elif ext == ".bmp":
            img.save(out, "BMP", **extra)
        elif ext == ".gif":
            img.save(out, "GIF")
        else:
            return None, "지원하지 않는 그림 형식"
        new = out.getvalue()
        if len(new) >= len(data):
            return None, "줄인 그림이 원본보다 작아지지 않음"
        return new, ""
    except Exception as exc:  # 그림 하나가 실패해도 문서는 계속
        return None, f"처리 실패: {type(exc).__name__}"


# ---------------------------------------------------------------- 문서 만들기

def build_candidate(src: Path, out: Path, max_long_edge: int, jpeg_quality: int,
                    cancel: Optional[Cancel] = None, progress: Optional[Progress] = None,
                    label: str = "") -> list[ImageResult]:
    """src(hwpx)의 그림을 줄여 out 에 새 hwpx 를 쓴다. 그림이 아닌 항목은 그대로 옮긴다."""
    results: list[ImageResult] = []
    with zipfile.ZipFile(src) as zin:
        infos = zin.infolist()
        # mimetype 은 압축하지 않고 맨 앞에 둔다(규격).
        infos.sort(key=lambda i: 0 if i.filename.lower() == "mimetype" else 1)
        images = [i for i in infos if is_image_resource(i.filename)]
        done = 0
        with zipfile.ZipFile(out, "w", allowZip64=True) as zout:
            for info in infos:
                if cancel and cancel():
                    raise Stopped()
                data = zin.read(info.filename)
                zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
                zi.external_attr = info.external_attr
                zi.comment = info.comment
                zi.compress_type = zipfile.ZIP_STORED if info.filename.lower() == "mimetype" else (
                    info.compress_type if info.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                    else zipfile.ZIP_DEFLATED)
                if is_image_resource(info.filename):
                    new, reason = optimize_image(data, info.filename, max_long_edge, jpeg_quality)
                    results.append(ImageResult(info.filename, len(data), len(new) if new else len(data),
                                               new is not None, reason))
                    if new is not None:
                        data = new
                    done += 1
                    if progress and (done == len(images) or done % 10 == 0):
                        progress(f"{label}그림 {done}/{len(images)}개 확인")
                zout.writestr(zi, data)
    return results


def validate_output(out: Path, original: Path) -> None:
    """결과 hwpx 를 다시 열어 원본 항목이 모두 있고 그림이 열리는지 본다."""
    try:
        with zipfile.ZipFile(original) as zo:
            want = {i.filename for i in zo.infolist() if not i.filename.endswith("/")}
        with zipfile.ZipFile(out) as z:
            if z.testzip() is not None:
                raise ValueError("결과 파일이 손상되었습니다.")
            have = {i.filename for i in z.infolist()}
            missing = sorted(want - have)
            if missing:
                raise ValueError(f"결과 파일을 만드는 중 일부 문서 내용이 빠졌습니다. (항목: {missing[0]})")
            names = z.namelist()
            if not names or names[0].lower() != "mimetype":
                raise ValueError("결과 파일의 형식 정보(mimetype)가 맨 앞에 있지 않습니다.")
            for n in names:
                if is_image_resource(n):
                    with Image.open(io.BytesIO(z.read(n))) as img:
                        img.load()
                        if img.size[0] <= 0 or img.size[1] <= 0:
                            raise ValueError("결과 그림이 올바르지 않습니다.")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("완성된 한글(hwpx) 파일을 확인하지 못했습니다.") from exc


def output_path_for(src: Path, folder: Optional[Path]) -> Path:
    folder = folder or src.parent
    base = folder / f"{src.stem}{OUTPUT_SUFFIX}.hwpx"
    if not base.exists():
        return base
    for n in range(1, 10000):
        cand = folder / f"{src.stem}{OUTPUT_SUFFIX}({n}).hwpx"
        if not cand.exists():
            return cand
    raise RuntimeError(f"저장할 이름을 정하지 못했습니다: {base.name}")


# ---------------------------------------------------------------- 파일 하나

def compress_file(path: Path, preset: Preset, output_dir: Optional[Path] = None,
                  converter: Optional[HancomConverter] = None,
                  progress: Optional[Progress] = None, cancel: Optional[Cancel] = None) -> dict:
    """파일 하나를 줄여 저장한다. 결과 정보를 돌려준다. 실패하면 이유를 담은 예외."""
    say = progress or (lambda _t: None)
    path = Path(path)
    original_bytes = path.stat().st_size
    work = Path(tempfile.mkdtemp(prefix="jbedu_hcz_"))
    try:
        converted = False
        src = path
        if is_old_hwp(path):
            if converter is None:
                raise HancomError("옛 한글(hwp) 파일을 바꿀 준비가 되지 않았습니다.")
            say(f"{path.name}: 한글로 hwpx 로 바꾸는 중")
            src = work / "converted.hwpx"
            converter.convert(path, src)
            converted = True
        check_hwpx(src)
        source_bytes = src.stat().st_size
        target_bytes = int(preset.target_mb * MB) if preset.target_mb > 0 else 0

        chosen = src
        images: list[ImageResult] = []
        note = ""
        if target_bytes and source_bytes <= target_bytes:
            note = "이미 목표 용량 이하라 그림을 줄이지 않았습니다."
        else:
            best: tuple[int, Path, list[ImageResult]] | None = None
            steps = attempts_for(preset)
            for n, (edge, quality) in enumerate(steps, start=1):
                if cancel and cancel():
                    raise Stopped()
                cand = work / f"attempt_{n}.hwpx"
                label = f"{path.name}: " + (f"{n}/{len(steps)}단계 " if len(steps) > 1 else "")
                imgs = build_candidate(src, cand, edge, quality, cancel, say, label)
                validate_output(cand, src)
                size = cand.stat().st_size
                if best is None or size < best[0]:
                    best = (size, cand, imgs)
                if target_bytes and size <= target_bytes:
                    break
            assert best is not None
            if best[0] < source_bytes:
                chosen, images = best[1], best[2]
            else:
                images = best[2]
                note = "줄일 수 있는 그림이 없어 그림은 그대로 두었습니다."

        out = output_path_for(path, output_dir)
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
        output_bytes = out.stat().st_size
        reduced_count = sum(1 for i in images if i.reduced) if chosen is not src else 0
        failed_images = [i for i in images if i.reason.startswith("처리 실패")]
        return {
            "name": path.name,
            "output": str(out),
            "original_bytes": original_bytes,
            "output_bytes": output_bytes,
            "converted": converted,
            "images_total": len(images),
            "images_reduced": reduced_count,
            "images_failed": len(failed_images),
            "target_mb": preset.target_mb,
            "target_reached": (output_bytes <= target_bytes) if target_bytes else None,
            "note": note,
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------- 여러 파일

def friendly_error(exc: BaseException) -> str:
    if isinstance(exc, PermissionError):
        return "파일을 읽거나 저장할 수 없습니다. 한글에서 파일을 닫았는지, 저장 폴더에 쓸 수 있는지 확인해 주세요."
    if isinstance(exc, (ValueError, HancomError, FileNotFoundError)):
        return str(exc).strip() or type(exc).__name__
    if isinstance(exc, OSError):
        return "파일을 읽거나 저장할 수 없습니다. 파일이 손상되지 않았는지, 저장 폴더에 쓸 수 있는지 확인해 주세요."
    return "문서를 처리하는 중 오류가 발생했습니다. 원본 파일은 바뀌지 않았습니다."


def compress_files(paths: list[Path], preset: Preset, output_dir: Optional[Path] = None,
                   progress: Optional[Progress] = None, cancel: Optional[Cancel] = None) -> dict:
    """여러 파일을 차례로 줄인다. 한 파일이 실패해도 나머지는 계속한다."""
    say = progress or (lambda _t: None)
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
                results.append(compress_file(p, preset, output_dir, converter, say, cancel))
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
    return {"results": results, "failed": failed, "stopped": stopped, "skipped": skipped}
