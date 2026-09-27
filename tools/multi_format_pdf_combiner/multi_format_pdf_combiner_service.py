from __future__ import annotations

import logging
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

# MuPDF(복구에 사용)는 깨진 PDF 를 만나면 "MuPDF error: ..." 를 stdout 으로 찍는다.
# 앱은 stdout 을 결과(JSON)로 읽으므로 불러올 때 한 번 stdout 밖으로 돌리고 표시를 끈다.
os.environ.setdefault("PYMUPDF_SUGGEST_LAYOUT_ANALYZER", "0")
import pymupdf  # noqa: E402
from pypdf import PdfReader, PdfWriter  # noqa: E402
# ImageOps·ImageSequence 는 설치본(PyInstaller)에 빠질 수 있어 Image 만 쓴다.
from PIL import Image  # noqa: E402

if hasattr(pymupdf, "no_recommend_layout"):
    pymupdf.no_recommend_layout()
try:
    pymupdf.set_messages(stream=sys.stderr)
except Exception:
    pass
try:
    pymupdf.TOOLS.mupdf_display_errors(False)
    pymupdf.TOOLS.mupdf_display_warnings(False)
except Exception:
    pass

# pypdf 경고("EOF marker not found" 등)가 오류 창에 영어로 섞이지 않게 줄인다.
logging.getLogger("pypdf").setLevel(logging.ERROR)

try:
    import pythoncom  # type: ignore
    import win32com.client  # type: ignore
    import win32com.client.dynamic  # type: ignore
    PYWIN32_AVAILABLE = True
except Exception:
    pythoncom = None
    win32com = None
    PYWIN32_AVAILABLE = False

SUPPORTED_IMG = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
# Word 가 여는 문서. 화면(toolSchemas.ts)이 .doc 도 고르게 한다.
SUPPORTED_DOCX = {".doc", ".docx"}
SUPPORTED_HWP = {".hwp", ".hwpx"}
SUPPORTED_PDF = {".pdf"}
SUPPORTED_PPT = {".ppt", ".pptx"}
SUPPORTED_ALL = SUPPORTED_PDF | SUPPORTED_IMG | SUPPORTED_DOCX | SUPPORTED_HWP | SUPPORTED_PPT

ProgressFn = Optional[Callable[[str], None]]

HWP_ALLOW_NOTICE = "한글에서 파일 접근 허용 창이 뜨면 [허용]을 눌러 주세요."


def describe_pdf_error(error: BaseException) -> str:
    """PDF 라이브러리의 영어 오류를 짧은 한국어 사유로 바꾼다. 이미 한국어면 그대로 둔다."""
    text = str(error).strip()
    probe = f"{type(error).__name__} {text} {error!r}".lower()
    if any(key in probe for key in ("decrypt", "encrypt", "password")):
        return "암호가 걸린 PDF라 열 수 없습니다. 암호를 해제한 뒤 다시 시도하세요."
    if any(key in probe for key in (
        "failed to open", "eof", "startxref", "xref", "stream has ended",
        "invalid pdf header", "/root", "trailer", "pdfreaderror", "pdfstreamerror",
        "filedataerror", "emptyfileerror", "not a pdf",
    )):
        return "PDF 파일이 손상되었거나 PDF 형식이 아닙니다."
    if re.search(r"[가-힣]", text):
        return text
    return f"처리하지 못했습니다. ({text or type(error).__name__})"


def wait_for_file_stable(path: Path, timeout_sec: float = 10.0, interval_sec: float = 0.25) -> None:
    start = time.time()
    last_size = -1
    same_count = 0
    while time.time() - start < timeout_sec:
        if not path.exists():
            time.sleep(interval_sec)
            continue
        try:
            sz = path.stat().st_size
        except Exception:
            time.sleep(interval_sec)
            continue

        if sz == last_size and sz > 0:
            same_count += 1
            if same_count >= 2:
                return
        else:
            same_count = 0
            last_size = sz

        time.sleep(interval_sec)


def is_pdf_file(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            head = f.read(5)
        return head == b"%PDF-"
    except Exception:
        return False


def human_size(num_bytes: int) -> str:
    n = float(num_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(n)} {unit}"
            return f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} TB"


def _safe_temp_name(ext: str) -> str:
    ext = (ext or "").lower()
    if not ext.startswith("."):
        ext = "." + ext
    return "input" + ext


def unique_temp_pdf(tmp_dir: Path, src: Path) -> Path:
    """변환 결과를 둘 임시 PDF 경로. 이름(확장자 뺀 부분)이 같은 입력이 여럿이어도
    (a/scan.jpg 와 b/scan.jpg, 보고서.hwp 와 보고서.docx) 서로 덮어쓰지 않게 번호를 붙인다."""
    tmp_dir = Path(tmp_dir)
    candidate = tmp_dir / f"{src.stem}.pdf"
    number = 1
    while candidate.exists():
        candidate = tmp_dir / f"{src.stem}({number}).pdf"
        number += 1
    # 자리를 먼저 잡아 두어 같은 이름을 두 번 고르지 않게 한다.
    candidate.touch()
    return candidate


def _rmtree_retry(path: Path, retries: int = 25, delay: float = 0.15) -> None:
    for _ in range(retries):
        try:
            shutil.rmtree(path, ignore_errors=False)
            return
        except Exception:
            time.sleep(delay)
    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass


def _register_hwp_security_module(hwp) -> Tuple[bool, str]:
    """한글의 파일 접근 보안 모듈을 등록한다. hwp_to_hwpx_converter 와 같은 순서로 시도한다."""
    module_names = [
        os.environ.get("HWP_FILE_PATH_CHECKER_MODULE", "").strip(),
        "SecurityModule",
        "FilePathCheckerModule",
        "FilePathCheckerModuleExample",
    ]
    tried: set = set()
    for module_name in module_names:
        if not module_name or module_name in tried:
            continue
        tried.add(module_name)
        try:
            if bool(hwp.RegisterModule("FilePathCheckDLL", module_name)):
                return True, module_name
        except Exception:
            continue
    return False, ""


def _set_hwp_visible(hwp, visible: bool) -> None:
    try:
        hwp.XHwpWindows.Item(0).Visible = visible
    except Exception:
        pass


def convert_with_hancom(input_path: Path, output_path: Path, progress: ProgressFn = None) -> Tuple[bool, str]:
    if not PYWIN32_AVAILABLE:
        return False, "pywin32(win32com/pythoncom) 미설치 또는 로드 실패"

    input_path = Path(input_path).resolve()
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pythoncom.CoInitialize()
    hwp = None
    temp_dir = None
    try:
        # 늦은 바인딩: gen_py 캐시가 깨진 PC 에서 "CLSIDToPackageMap" 오류가 나지 않게 한다.
        try:
            hwp = win32com.client.dynamic.Dispatch("HWPFrame.HwpObject")
        except Exception as e:
            return False, f"한글(HWP)을 실행할 수 없습니다. 한글 설치 여부를 확인하세요. ({e})"

        registered, _module_name = _register_hwp_security_module(hwp)
        if registered:
            _set_hwp_visible(hwp, False)
        else:
            # 보안 모듈이 없으면 한글이 파일 접근 허용 창을 띄운다. 창을 숨기면
            # 그 질문이 안 보여 작업이 멈춘 것처럼 되므로 한글 창을 보이게 둔다.
            _set_hwp_visible(hwp, True)
            if progress is not None:
                progress(f"{input_path.name}: {HWP_ALLOW_NOTICE}")

        temp_dir = Path(tempfile.mkdtemp(prefix="hwp2pdf_"))
        ext = input_path.suffix.lower()
        tmp_in = temp_dir / _safe_temp_name(ext)
        tmp_out = temp_dir / "output.pdf"

        shutil.copy2(str(input_path), str(tmp_in))

        try:
            hwp.Open(str(tmp_in), "", "")
        except Exception:
            hwp.Open(str(tmp_in))

        try:
            ps = hwp.HParameterSet.HFileOpenSave
            hwp.HAction.GetDefault("FileSaveAs", ps.HSet)
            ps.filename = str(tmp_out)
            ps.Format = "PDF"
            hwp.HAction.Execute("FileSaveAs", ps.HSet)
        except Exception as e:
            try:
                hwp.SaveAs(str(tmp_out), "PDF")
            except Exception:
                return False, f"PDF 저장 실패: {e}"

        wait_for_file_stable(tmp_out)

        if (not tmp_out.exists()) or tmp_out.stat().st_size == 0:
            return False, "PDF 생성 실패(파일이 생성되지 않음)"
        if not is_pdf_file(tmp_out):
            return False, "PDF 생성 실패(%PDF- 헤더 불일치)"

        try:
            if output_path.exists():
                output_path.unlink(missing_ok=True)
            shutil.move(str(tmp_out), str(output_path))
        except Exception:
            shutil.copy2(str(tmp_out), str(output_path))

        return True, "OK"

    except Exception as e:
        return False, f"변환 중 오류: {e}"

    finally:
        try:
            if hwp is not None:
                try:
                    hwp.Clear(1)
                except Exception:
                    pass
                try:
                    hwp.Quit()
                except Exception:
                    pass
        finally:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass
            if temp_dir is not None and temp_dir.exists():
                _rmtree_retry(temp_dir)


def convert_with_word(input_path: Path, output_path: Path) -> Tuple[bool, str]:
    """.doc/.docx 를 Word 로 PDF 로 저장한다. 사용자가 열어 둔 Word 를 건드리지 않게 새 Word 를 띄운다."""
    if not PYWIN32_AVAILABLE:
        return False, "pywin32(win32com/pythoncom) 미설치 또는 로드 실패"

    input_path = Path(input_path).resolve()
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pythoncom.CoInitialize()
    word = None
    temp_dir = None
    try:
        temp_dir = Path(tempfile.mkdtemp(prefix="docx2pdf_"))
        # 확장자를 그대로 둬야 Word 가 .doc(예전 형식)도 제대로 연다.
        tmp_in = temp_dir / _safe_temp_name(input_path.suffix)
        tmp_out = temp_dir / "output.pdf"
        shutil.copy2(str(input_path), str(tmp_in))

        # Dispatch 는 이미 떠 있는 사용자의 Word 에 붙는다. 그러면 Visible=False·Quit() 가
        # 사용자가 작업하던 문서까지 숨기거나 닫는다. DispatchEx 로 따로 띄운다.
        try:
            word = win32com.client.DispatchEx("Word.Application")
        except Exception as e:
            return False, f"Word를 실행할 수 없습니다. Microsoft Word 설치 여부를 확인하세요. ({e})"
        word.Visible = False
        try:
            word.DisplayAlerts = 0
        except Exception:
            pass

        doc = word.Documents.Open(str(tmp_in))
        try:
            doc.ExportAsFixedFormat(OutputFileName=str(tmp_out), ExportFormat=17)
        finally:
            doc.Close(False)

        wait_for_file_stable(tmp_out)

        if (not tmp_out.exists()) or tmp_out.stat().st_size == 0:
            return False, "PDF 생성 실패(파일이 생성되지 않음)"
        if not is_pdf_file(tmp_out):
            return False, "PDF 생성 실패(%PDF- 헤더 불일치)"

        try:
            if output_path.exists():
                output_path.unlink(missing_ok=True)
            shutil.move(str(tmp_out), str(output_path))
        except Exception:
            shutil.copy2(str(tmp_out), str(output_path))

        return True, "OK"

    except Exception as e:
        return False, f"Word 변환 실패: {e}"

    finally:
        try:
            if word is not None:
                try:
                    word.Quit()
                except Exception:
                    pass
        finally:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass
            if temp_dir is not None and temp_dir.exists():
                _rmtree_retry(temp_dir)


def convert_with_powerpoint(input_path: Path, output_path: Path) -> Tuple[bool, str]:
    if not PYWIN32_AVAILABLE:
        return False, "pywin32(win32com/pythoncom) 미설치 또는 로드 실패"

    input_path = Path(input_path).resolve()
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pythoncom.CoInitialize()
    ppt = None
    ppt_in_use = False
    temp_dir = None
    try:
        temp_dir = Path(tempfile.mkdtemp(prefix="ppt2pdf_"))
        ext = input_path.suffix.lower()
        tmp_in = temp_dir / _safe_temp_name(ext)
        tmp_out = temp_dir / "output.pdf"
        shutil.copy2(str(input_path), str(tmp_in))

        # DispatchEx 로 새로 띄운다. 다만 PowerPoint 는 한 번에 하나만 떠서 사용자가
        # 이미 열어 둔 PowerPoint 에 붙을 수 있으므로, 그때는 끝나고 Quit() 하지 않는다.
        try:
            ppt = win32com.client.DispatchEx("PowerPoint.Application")
        except Exception as e:
            return False, f"PowerPoint를 실행할 수 없습니다. PowerPoint 설치 여부를 확인하세요. ({e})"
        try:
            if int(ppt.Presentations.Count) > 0:
                ppt_in_use = True
        except Exception:
            pass
        try:
            ppt.Visible = 1
        except Exception:
            pass

        pres = None
        try:
            try:
                pres = ppt.Presentations.Open(str(tmp_in), WithWindow=False)
            except Exception:
                pres = ppt.Presentations.Open(str(tmp_in))
            pres.SaveAs(str(tmp_out), 32)
        finally:
            try:
                if pres is not None:
                    pres.Close()
            except Exception:
                pass

        wait_for_file_stable(tmp_out)

        if (not tmp_out.exists()) or tmp_out.stat().st_size == 0:
            return False, "PDF 생성 실패(파일이 생성되지 않음)"
        if not is_pdf_file(tmp_out):
            return False, "PDF 생성 실패(%PDF- 헤더 불일치)"

        try:
            if output_path.exists():
                output_path.unlink(missing_ok=True)
            shutil.move(str(tmp_out), str(output_path))
        except Exception:
            shutil.copy2(str(tmp_out), str(output_path))

        return True, "OK"

    except Exception as e:
        return False, f"PowerPoint 변환 실패: {e}"

    finally:
        try:
            if ppt is not None and not ppt_in_use:
                try:
                    ppt.Quit()
                except Exception:
                    pass
        finally:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass
            if temp_dir is not None and temp_dir.exists():
                _rmtree_retry(temp_dir)


def _image_frame_to_pdf_ready(frame: Image.Image) -> Image.Image:
    """PDF 로 저장할 수 있는 RGB/L 이미지로 바꾼다. 16비트·투명·팔레트·CMYK 등 어떤 모드든 받는다."""
    mode = frame.mode
    if mode in ("RGB", "L", "CMYK", "1"):
        return frame
    if mode.startswith("I") or mode == "F":
        # 16비트 흑백 등: 그대로 L 로 바꾸면 255 를 넘는 값이 모두 흰색이 된다. 범위를 줄여 옮긴다.
        gray = frame.convert("F")
        low, high = gray.getextrema()
        top = 65535.0 if high > 255 and high <= 65535 else float(high or 1)
        if top <= 255:
            top = 255.0
        return gray.point(lambda value: value * 255.0 / top).convert("L")
    if mode in ("RGBA", "LA", "PA") or (mode == "P" and "transparency" in frame.info):
        rgba = frame.convert("RGBA")
        canvas = Image.new("RGB", rgba.size, (255, 255, 255))
        canvas.paste(rgba, mask=rgba.getchannel("A"))
        return canvas
    return frame.convert("RGB")


# EXIF 방향 값 → 똑바로 세우는 변환 (PIL.ImageOps.exif_transpose 와 같은 표)
_EXIF_ORIENTATION = {
    2: Image.Transpose.FLIP_LEFT_RIGHT,
    3: Image.Transpose.ROTATE_180,
    4: Image.Transpose.FLIP_TOP_BOTTOM,
    5: Image.Transpose.TRANSPOSE,
    6: Image.Transpose.ROTATE_270,
    7: Image.Transpose.TRANSVERSE,
    8: Image.Transpose.ROTATE_90,
}


def _upright(frame: Image.Image, orientation) -> Image.Image:
    method = _EXIF_ORIENTATION.get(orientation)
    return frame.transpose(method) if method is not None else frame


def image_to_pdf(src: Path, out: Path) -> None:
    """이미지를 PDF 로. 사진의 회전 정보(EXIF)를 반영하고, 여러 쪽 TIFF 는 모든 쪽을 넣는다."""
    with Image.open(src) as im:
        pages = []
        # 여러 쪽은 TIFF 만 쪽으로 본다(움직이는 WEBP 의 장면을 쪽으로 늘어놓지 않게).
        count = int(getattr(im, "n_frames", 1) or 1) if src.suffix.lower() in (".tif", ".tiff") else 1
        for index in range(max(1, count)):
            im.seek(index)
            try:
                orientation = im.getexif().get(0x0112)
            except Exception:
                orientation = None
            pages.append(_image_frame_to_pdf_ready(_upright(im.copy(), orientation)))
        first, rest = pages[0], pages[1:]
        first.save(out, "PDF", save_all=bool(rest), append_images=rest)


def ensure_pdf(src: Path, tmp_dir: Path, progress: ProgressFn = None) -> Tuple[Optional[Path], Optional[str]]:
    ext = src.suffix.lower()

    if ext in SUPPORTED_PDF:
        return (src, None) if is_pdf_file(src) else (None, "PDF 파일이 아니거나 손상되었습니다.")

    if ext in SUPPORTED_IMG:
        out = unique_temp_pdf(tmp_dir, src)
        try:
            image_to_pdf(src, out)
            wait_for_file_stable(out)
            return (out, None) if is_pdf_file(out) else (None, "이미지를 PDF로 바꾸지 못했습니다.")
        except Exception as e:
            return None, f"이미지를 PDF로 바꾸지 못했습니다. ({e})"

    if ext in SUPPORTED_DOCX:
        out = unique_temp_pdf(tmp_dir, src)
        ok, msg = convert_with_word(src, out)
        return (out, None) if ok else (None, msg)

    if ext in SUPPORTED_HWP:
        out = unique_temp_pdf(tmp_dir, src)
        ok, msg = convert_with_hancom(src, out, progress)
        return (out, None) if ok else (None, msg)

    if ext in SUPPORTED_PPT:
        out = unique_temp_pdf(tmp_dir, src)
        ok, msg = convert_with_powerpoint(src, out)
        return (out, None) if ok else (None, msg)

    return None, "지원하지 않는 파일 형식입니다."


def repair_pdf_if_needed(src_pdf: Path, tmp_dir: Path) -> Path:
    """손상된 PDF 를 PyMuPDF 로 열어(자동 복구) 새로 저장한다. 실패하면 원본 경로를 돌려준다.
    설치본에 함께 들어가는 PyMuPDF 만 쓴다(pikepdf 는 설치본에 없다)."""
    repaired = Path(tmp_dir) / f"{src_pdf.stem}__repaired.pdf"
    number = 1
    while repaired.exists():
        repaired = Path(tmp_dir) / f"{src_pdf.stem}__repaired({number}).pdf"
        number += 1
    try:
        doc = pymupdf.open(str(src_pdf), filetype="pdf")
    except Exception:
        return src_pdf
    try:
        if doc.needs_pass or doc.page_count == 0:
            return src_pdf
        doc.save(str(repaired), garbage=3, clean=True, deflate=True)
    except Exception:
        return src_pdf
    finally:
        doc.close()
    if repaired.exists() and repaired.stat().st_size > 0 and is_pdf_file(repaired):
        return repaired
    return src_pdf


class _EncryptedPdf(RuntimeError):
    pass


def merge_pdf_ordered(
    pdf_paths: List[Path],
    output_path: Path,
    names: Optional[Sequence[str]] = None,
) -> Tuple[List[str], List[Tuple[str, str]]]:
    """PDF 를 순서대로 합친다. names 를 주면 결과·실패 목록에 그 이름(원본 파일 이름)을 쓴다."""
    if not pdf_paths:
        raise ValueError("병합할 파일이 없습니다.")

    writer = PdfWriter()
    ok_files: List[str] = []
    bad_files: List[Tuple[str, str]] = []
    labels = list(names) if names is not None else [Path(fp).name for fp in pdf_paths]

    # 복구본은 사용자 폴더가 아니라 임시 폴더에 둔다.
    tmp_dir = Path(tempfile.mkdtemp(prefix="jbedu_pdf_repair_"))

    try:
        for fp, label in zip(pdf_paths, labels):
            fp = Path(fp)
            if not is_pdf_file(fp):
                bad_files.append((label, "PDF 파일이 아니거나 손상되었습니다."))
                continue

            try:
                reader = PdfReader(str(fp), strict=False)

                if getattr(reader, "is_encrypted", False):
                    try:
                        if reader.decrypt("") == 0:
                            raise _EncryptedPdf()
                    except Exception:
                        raise _EncryptedPdf()

                pages = list(reader.pages)
                for page in pages:
                    writer.add_page(page)
                ok_files.append(label)

            except _EncryptedPdf:
                bad_files.append((label, "암호가 걸린 PDF라 합칠 수 없습니다. 암호를 해제한 뒤 다시 시도하세요."))
                continue
            except Exception as e1:
                try:
                    repaired = repair_pdf_if_needed(fp, tmp_dir)
                    if repaired != fp:
                        reader2 = PdfReader(str(repaired), strict=False)
                        for page in list(reader2.pages):
                            writer.add_page(page)
                        ok_files.append(label + " (복구 후 병합)")
                        continue
                except Exception:
                    pass
                bad_files.append((label, describe_pdf_error(e1)))

        if len(writer.pages) == 0:
            msg = "병합할 페이지가 없습니다.\n"
            if bad_files:
                msg += "\n[실패 파일]\n" + "\n".join([f"- {n}: {err}" for n, err in bad_files[:10]])
            raise RuntimeError(msg)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            writer.write(f)

        return ok_files, bad_files

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)