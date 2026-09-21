"""PDF 용량 압축.

문서 안의 사진(이미지)만 해상도를 낮추고 JPEG 로 다시 저장한다.
글자·표·도형(벡터)과 글꼴은 손대지 않으므로 내용이 바뀌거나 사라지지 않는다.

예전에는 Ghostscript 로 PDF 전체를 새로 그려 만들었다. 그 방식은 파일에 따라
벡터 내용이 통째로 빠진 PDF 를 오류 없이 만들어 내는 일이 있었고(10.07.1),
큰 파일은 시도마다 전체를 다시 그려 오래 걸렸다.
"""
from __future__ import annotations

import io
import shutil
import tempfile
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import pymupdf
from PIL import Image

# (이미지 최대 해상도 dpi, JPEG 품질). 약한 것부터 차례로 시도한다.
LEVELS: List[Tuple[int, int]] = [
    (200, 85), (170, 80), (150, 75), (130, 70), (110, 65),
    (100, 60), (90, 50), (80, 45), (72, 40),
]

# 이보다 작은 이미지는 다시 저장해도 이득이 없다.
_MIN_IMAGE_BYTES = 4096

# 단계를 낮춰도 이 비율 넘게 줄지 않는 일이 연달아 생기면 그만한다.
# 사진이 거의 없고 글자·도형 위주인 파일은 더 줄일 수 없다.
_STALL_RATIO = 0.02
_STALL_LIMIT = 2


class CompressCancelled(RuntimeError):
    pass


def bytes_to_mb(n: int) -> float:
    return n / (1024 * 1024)


def safe_output_path(in_fp: Path, target_mb: float = 0, folder: Optional[Path] = None) -> Path:
    """'원본이름_압축.pdf'. 같은 이름이 있으면 번호를 붙인다. target_mb 는 예전 호출과 맞추려고 남겨 둔다."""
    base = folder if folder is not None else in_fp.parent
    return unique_path(base / f"{in_fp.stem}_압축.pdf")


def _open(in_fp: Path) -> pymupdf.Document:
    doc = pymupdf.open(str(in_fp))
    if doc.needs_pass and not doc.authenticate(""):
        doc.close()
        raise RuntimeError(f"암호가 걸린 PDF 라 압축할 수 없습니다: {in_fp.name}")
    return doc


def _image_ppi(doc: pymupdf.Document) -> Dict[int, float]:
    """이미지마다 페이지에 실제로 찍힌 크기로 계산한 가장 높은 해상도(ppi)."""
    ppi: Dict[int, float] = {}
    for page in doc:
        for info in page.get_images(full=True):
            xref, width = info[0], info[2]
            try:
                rects = page.get_image_rects(xref)
            except Exception:
                rects = []
            for rect in rects:
                if rect.width > 0:
                    ppi[xref] = max(ppi.get(xref, 0.0), width / (rect.width / 72.0))
    return ppi


def _recompress_images(doc: pymupdf.Document, dpi: int, quality: int,
                       cancel: Optional[Callable[[], bool]]) -> int:
    """문서 안 이미지를 dpi·품질에 맞춰 다시 저장한다. 바꾼 개수를 돌려준다."""
    images: Dict[int, tuple] = {}
    smasks = set()
    for page in doc:
        for info in page.get_images(full=True):
            images[info[0]] = info
            if info[1]:
                smasks.add(info[1])
    ppi = _image_ppi(doc)

    changed = 0
    for xref, info in images.items():
        if cancel is not None and cancel():
            raise CompressCancelled("중지 요청으로 압축을 멈췄습니다.")
        # 투명도 마스크는 원래대로 두고 본 이미지만 바꾼다(투명 배경 유지).
        if xref in smasks:
            continue
        bpc = info[4]
        # 글자 모양을 찍는 스텐실 마스크, 1비트 흑백, 색 지정 투명은 JPEG 로 바꾸면 망가진다.
        if (doc.xref_get_key(xref, "ImageMask")[1] == "true"
                or bpc == 1
                or doc.xref_get_key(xref, "Mask")[0] != "null"):
            continue
        try:
            raw = doc.xref_stream_raw(xref) or b""
        except Exception:
            continue
        if len(raw) < _MIN_IMAGE_BYTES:
            continue
        try:
            pix = pymupdf.Pixmap(doc, xref)
            if pix.alpha:
                pix = pymupdf.Pixmap(pix, 0)
            if pix.colorspace is None or pix.colorspace.n not in (1, 3):
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
            mode = "L" if pix.n == 1 else "RGB"
            img = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
        except Exception:
            # 읽지 못하는 형식은 원래대로 둔다.
            continue

        cur_ppi = ppi.get(xref, 0.0)
        if cur_ppi > dpi:
            scale = dpi / cur_ppi
            img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                             Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=quality, optimize=True)
        data = buf.getvalue()
        if len(data) >= len(raw):
            continue

        doc.update_stream(xref, data, compress=False)
        doc.xref_set_key(xref, "Filter", "/DCTDecode")
        doc.xref_set_key(xref, "DecodeParms", "null")
        doc.xref_set_key(xref, "Decode", "null")
        doc.xref_set_key(xref, "Width", str(img.width))
        doc.xref_set_key(xref, "Height", str(img.height))
        doc.xref_set_key(xref, "BitsPerComponent", "8")
        doc.xref_set_key(xref, "ColorSpace", "/DeviceGray" if mode == "L" else "/DeviceRGB")
        changed += 1
    return changed


def compress_once(in_fp: Path, out_fp: Path, dpi: int, quality: int,
                  cancel: Optional[Callable[[], bool]] = None) -> int:
    """한 단계로 압축해 out_fp 에 저장하고 크기를 돌려준다."""
    doc = _open(in_fp)
    try:
        _recompress_images(doc, dpi, quality, cancel)
        doc.save(str(out_fp), garbage=4, deflate=True, deflate_fonts=True, use_objstms=1)
    finally:
        doc.close()
    return out_fp.stat().st_size


def compress_to_target(in_fp: Path, out_fp: Path, target_bytes: int, max_tries: int,
                       progress: Optional[Callable[[str], None]] = None,
                       cancel: Optional[Callable[[], bool]] = None) -> Tuple[int, bool]:
    """목표 용량 이하가 될 때까지 단계를 높여 가며 압축한다.

    반환: (결과 크기 bytes, 목표 달성 여부). 목표에 못 미치면 가장 작게 나온 결과를 저장한다.
    """
    def say(text: str) -> None:
        if progress is not None:
            progress(text)

    in_size = in_fp.stat().st_size
    if in_size <= target_bytes:
        if in_fp.resolve() != out_fp.resolve():
            shutil.copyfile(in_fp, out_fp)
        say(f"{in_fp.name}: 이미 목표 용량 이하({bytes_to_mb(in_size):.2f}MB)라 그대로 복사했습니다.")
        return in_size, True

    work_dir = Path(tempfile.mkdtemp(prefix="jbedu_pdfc_"))
    best: Optional[Tuple[int, Path]] = None
    try:
        prev = 0
        stall = 0
        for tries, (dpi, quality) in enumerate(LEVELS[:max(1, int(max_tries))], start=1):
            if cancel is not None and cancel():
                raise CompressCancelled("중지 요청으로 압축을 멈췄습니다.")
            say(f"{in_fp.name}: {tries}단계 (사진 {dpi}dpi, 화질 {quality}) 압축 중…")
            tmp = work_dir / f"try_{tries:02d}.pdf"
            size = compress_once(in_fp, tmp, dpi, quality, cancel)
            say(f"{in_fp.name}: {tries}단계 결과 {bytes_to_mb(size):.2f}MB "
                f"(목표 {bytes_to_mb(target_bytes):.2f}MB)")
            if best is None or size < best[0]:
                best = (size, tmp)
            if size <= target_bytes:
                break
            stall = stall + 1 if prev and (prev - size) < prev * _STALL_RATIO else 0
            prev = size
            if stall >= _STALL_LIMIT:
                say(f"{in_fp.name}: 사진을 더 줄여도 용량이 줄지 않습니다. "
                    "글자·도형 위주라 이 이상은 줄일 수 없습니다.")
                break

        if best is None:
            raise RuntimeError(f"압축 결과를 만들지 못했습니다: {in_fp.name}")
        # 압축해도 원본보다 작아지지 않으면 원본을 그대로 쓴다.
        if best[0] >= in_size:
            shutil.copyfile(in_fp, out_fp)
            return in_size, in_size <= target_bytes
        if out_fp.exists():
            out_fp.unlink()
        shutil.move(str(best[1]), str(out_fp))
        return best[0], best[0] <= target_bytes
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def unique_path(path: Path, folder: bool = False) -> Path:
    """같은 이름이 이미 있으면 '이름(1).확장자', '이름(2).확장자' 처럼 번호를 붙인다.
    결과물이 기존 파일을 덮어쓰지 않게 한다. folder=True 면 확장자 없이 이름 뒤에 붙인다."""
    if not path.exists():
        return path
    for number in range(1, 10000):
        if folder:
            candidate = path.with_name(f"{path.name}({number})")
        else:
            candidate = path.with_name(f"{path.stem}({number}){path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"저장할 이름을 정하지 못했습니다: {path.name}")



def compress_group_to_total(
    inputs: List[Path],
    out_root: Path,
    total_bytes: int,
    progress: Optional[Callable[[str], None]] = None,
    cancel: Optional[Callable[[], bool]] = None,
) -> dict:
    """여러 PDF 의 합계가 total_bytes 이하가 되도록 파일마다 압축 단계를 고른다.

    모든 파일을 원본(0단계)에서 출발해, 합계가 목표를 넘는 동안
    '한 단계 더 압축했을 때 가장 많이 줄어드는 파일'을 골라 그 파일만 한 단계 올린다.
    잘 줄어드는 사진 위주 파일은 더 줄이고, 글자 위주·작은 파일은 원본에 가깝게 둔다.
    결과는 out_root 아래 새 폴더에 원래 파일명 그대로 저장한다.
    압축하지 못한 파일(암호 등)은 원본을 그대로 넣고 failed 에 적는다.
    """
    import datetime

    def say(text: str) -> None:
        if progress is not None:
            progress(text)

    def check_cancel() -> None:
        if cancel is not None and cancel():
            raise CompressCancelled("중지 요청으로 압축을 멈췄습니다.")

    work_dir = Path(tempfile.mkdtemp(prefix="jbedu_pdfg_"))
    try:
        # 파일마다: 원본 크기, 단계별 결과(크기·임시 파일), 지금 고른 단계.
        states = []
        for index, path in enumerate(inputs):
            states.append({
                "path": path,
                "original": path.stat().st_size,
                "sizes": {0: path.stat().st_size},
                "files": {0: path},
                "level": 0,
                "done": False,
                "error": "",
                "slot": index,
            })

        def measure(state: dict, level: int) -> int:
            """level 단계로 압축했을 때의 크기. 한 번 잰 것은 다시 만들지 않는다."""
            if level in state["sizes"]:
                return state["sizes"][level]
            check_cancel()
            dpi, quality = LEVELS[level - 1]
            tmp = work_dir / f"f{state['slot']:03d}_l{level}.pdf"
            size = compress_once(state["path"], tmp, dpi, quality, cancel)
            state["sizes"][level] = size
            state["files"][level] = tmp
            return size

        def next_step(state: dict):
            """지금 단계보다 실제로 더 작아지는 가장 가까운 단계와 그만큼 줄어드는 크기.
            두 단계를 더 봐도 줄지 않으면 이 파일은 더 줄일 수 없는 것으로 본다."""
            current = state["sizes"][state["level"]]
            for level in range(state["level"] + 1, min(state["level"] + 3, len(LEVELS) + 1)):
                size = measure(state, level)
                if size < current * 0.995:
                    return level, current - size
            return None

        total = sum(state["original"] for state in states)
        say(f"PDF {len(states)}개, 합계 {bytes_to_mb(total):.2f}MB → 목표 {bytes_to_mb(total_bytes):.2f}MB")

        steps = 0
        while total > total_bytes:
            check_cancel()
            best = None
            for state in states:
                if state["done"]:
                    continue
                try:
                    step = next_step(state)
                except CompressCancelled:
                    raise
                except Exception as error:  # 이 파일만 원본 그대로 두고 넘어간다.
                    state["error"] = str(error) or type(error).__name__
                    state["level"] = 0
                    state["done"] = True
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
            steps += 1
            say(
                f"{state['path'].name}: {level}단계로 줄임 → 합계 {bytes_to_mb(total):.2f}MB"
            )

        # 결과 폴더에 원래 이름으로 저장한다.
        stamp = datetime.datetime.now().strftime("%m%d_%H%M")
        target_label = f"{bytes_to_mb(total_bytes):g}".rstrip(".")
        folder = unique_path(out_root / f"PDF압축_합계{target_label}MB_{stamp}", folder=True)
        folder.mkdir(parents=True, exist_ok=True)

        results = []
        failed = []
        for state in states:
            chosen = state["files"][state["level"]]
            target = unique_path(folder / state["path"].name)
            shutil.copyfile(chosen, target)
            size = target.stat().st_size
            results.append({
                "path": target,
                # 이름이 겹쳐 번호가 붙었으면 실제로 저장된 이름을 보여 준다.
                "name": target.name,
                "original_mb": round(bytes_to_mb(state["original"]), 2),
                "size_mb": round(bytes_to_mb(size), 2),
                "level": state["level"],
            })
            if state["error"]:
                failed.append({"name": state["path"].name, "error": state["error"]})

        final_total = sum(item["path"].stat().st_size for item in results)
        return {
            "folder": folder,
            "results": results,
            "failed": failed,
            "original_total": sum(state["original"] for state in states),
            "final_total": final_total,
            "target_bytes": total_bytes,
            "achieved": final_total <= total_bytes,
        }
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
