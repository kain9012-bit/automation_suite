from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path
from typing import List, Optional, Tuple

from pypdf import PdfReader, PdfWriter
from PIL import Image

try:
    import pikepdf  # type: ignore
    PIKEPDF_AVAILABLE = True
except Exception:
    pikepdf = None
    PIKEPDF_AVAILABLE = False

try:
    import pythoncom  # type: ignore
    import win32com.client  # type: ignore
    PYWIN32_AVAILABLE = True
except Exception:
    pythoncom = None
    win32com = None
    PYWIN32_AVAILABLE = False

SUPPORTED_IMG = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
SUPPORTED_DOCX = {".docx"}
SUPPORTED_HWP = {".hwp", ".hwpx"}
SUPPORTED_PDF = {".pdf"}
SUPPORTED_PPT = {".ppt", ".pptx"}
SUPPORTED_ALL = SUPPORTED_PDF | SUPPORTED_IMG | SUPPORTED_DOCX | SUPPORTED_HWP | SUPPORTED_PPT


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


def convert_with_hancom(input_path: Path, output_path: Path) -> Tuple[bool, str]:
    if not PYWIN32_AVAILABLE:
        return False, "pywin32(win32com/pythoncom) 미설치 또는 로드 실패"

    input_path = Path(input_path).resolve()
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pythoncom.CoInitialize()
    hwp = None
    temp_dir = None
    try:
        hwp = win32com.client.Dispatch("HWPFrame.HwpObject")
        try:
            hwp.RegisterModule("FilePathCheckDLL", "SecurityModule")
        except Exception:
            pass

        try:
            hwp.XHwpWindows.Item(0).Visible = False
        except Exception:
            pass

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
        tmp_in = temp_dir / "input.docx"
        tmp_out = temp_dir / "output.pdf"
        shutil.copy2(str(input_path), str(tmp_in))

        word = win32com.client.Dispatch("Word.Application")
        word.Visible = False

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
    temp_dir = None
    try:
        temp_dir = Path(tempfile.mkdtemp(prefix="ppt2pdf_"))
        ext = input_path.suffix.lower()
        tmp_in = temp_dir / _safe_temp_name(ext)
        tmp_out = temp_dir / "output.pdf"
        shutil.copy2(str(input_path), str(tmp_in))

        ppt = win32com.client.Dispatch("PowerPoint.Application")
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
            if ppt is not None:
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


def ensure_pdf(src: Path, tmp_dir: Path) -> Tuple[Optional[Path], Optional[str]]:
    ext = src.suffix.lower()

    if ext in SUPPORTED_PDF:
        return (src, None) if is_pdf_file(src) else (None, "PDF 헤더 불일치")

    if ext in SUPPORTED_IMG:
        out = tmp_dir / f"{src.stem}.pdf"
        try:
            with Image.open(src) as im:
                if im.mode in ("RGBA", "P"):
                    im = im.convert("RGB")
                im.save(out, "PDF")
            wait_for_file_stable(out)
            return (out, None) if is_pdf_file(out) else (None, "이미지→PDF 후 헤더 불일치")
        except Exception as e:
            return None, f"이미지→PDF 실패: {e}"

    if ext in SUPPORTED_DOCX:
        out = tmp_dir / f"{src.stem}.pdf"
        ok, msg = convert_with_word(src, out)
        return (out, None) if ok else (None, msg)

    if ext in SUPPORTED_HWP:
        out = tmp_dir / f"{src.stem}.pdf"
        ok, msg = convert_with_hancom(src, out)
        return (out, None) if ok else (None, msg)

    if ext in SUPPORTED_PPT:
        out = tmp_dir / f"{src.stem}.pdf"
        ok, msg = convert_with_powerpoint(src, out)
        return (out, None) if ok else (None, msg)

    return None, "지원하지 않는 확장자"


def repair_pdf_if_needed(src_pdf: Path, tmp_dir: Path) -> Path:
    if not PIKEPDF_AVAILABLE:
        return src_pdf

    repaired = tmp_dir / f"{src_pdf.stem}__repaired.pdf"
    try:
        with pikepdf.open(str(src_pdf)) as pdf:
            pdf.save(str(repaired))
        wait_for_file_stable(repaired)
        if repaired.exists() and repaired.stat().st_size > 0 and is_pdf_file(repaired):
            return repaired
    except Exception:
        pass
    return src_pdf


def merge_pdf_ordered(pdf_paths: List[Path], output_path: Path) -> Tuple[List[str], List[Tuple[str, str]]]:
    if not pdf_paths:
        raise ValueError("병합할 파일이 없습니다.")

    writer = PdfWriter()
    ok_files: List[str] = []
    bad_files: List[Tuple[str, str]] = []

    tmp_dir = output_path.parent / "_tmp_pdf_repair"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    try:
        for fp in pdf_paths:
            if not is_pdf_file(fp):
                bad_files.append((fp.name, "PDF 헤더 불일치"))
                continue

            try:
                reader = PdfReader(str(fp), strict=False)

                if getattr(reader, "is_encrypted", False):
                    try:
                        if reader.decrypt("") == 0:
                            raise RuntimeError("암호화된 PDF(비밀번호 필요)")
                    except Exception:
                        raise RuntimeError("암호화된 PDF(비밀번호 필요)")

                for page in reader.pages:
                    writer.add_page(page)
                ok_files.append(fp.name)

            except Exception as e1:
                try:
                    repaired = repair_pdf_if_needed(fp, tmp_dir)
                    if repaired != fp:
                        reader2 = PdfReader(str(repaired), strict=False)
                        for page in reader2.pages:
                            writer.add_page(page)
                        ok_files.append(fp.name + " (복구 후 병합)")
                        continue
                except Exception as e2:
                    bad_files.append((fp.name, f"{e1} / 복구실패: {e2}"))
                    continue

                bad_files.append((fp.name, str(e1)))

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