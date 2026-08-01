from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path
from typing import Tuple

import pythoncom
import win32com.client


SUPPORTED_EXTS = {".hwp", ".hwpx"}


def is_supported_hwp_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_EXTS


def list_hwp_files_in_folder(folder: Path) -> list[Path]:
    return sorted([p.resolve() for p in folder.iterdir() if is_supported_hwp_file(p)])


def safe_basename(name: str) -> str:
    n = (name or "").strip()
    n = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", n)
    n = re.sub(r"\s+", " ", n).strip()
    n = re.sub(r"[\.\s]+$", "", n)
    return n or "output"


def _safe_temp_name(ext: str) -> str:
    ext = (ext or "").lower()
    if not ext.startswith("."):
        ext = "." + ext
    return "input" + ext


def convert_with_hancom(input_path: Path, output_path: Path) -> Tuple[bool, str]:
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

        # 원본 프로그램처럼 임시폴더에 복사해서 열기
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

        if not tmp_out.exists() or tmp_out.stat().st_size == 0:
            return False, "PDF 파일이 생성되지 않았습니다."

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
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except Exception:
                    pass


def build_output_pdf_path(src: Path, output_dir: Path) -> Path:
    base = safe_basename(src.stem)
    return output_dir / f"{base}.pdf"


def convert_files(file_paths: list[Path], output_dir: Path) -> tuple[list[str], list[tuple[str, str]]]:
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    ok_files: list[str] = []
    bad_files: list[tuple[str, str]] = []

    for src in file_paths:
        src = Path(src).resolve()

        if not src.exists():
            bad_files.append((src.name, "파일이 존재하지 않습니다."))
            continue

        if src.suffix.lower() not in SUPPORTED_EXTS:
            bad_files.append((src.name, "지원하지 않는 확장자입니다."))
            continue

        out_pdf = build_output_pdf_path(src, output_dir)
        ok, msg = convert_with_hancom(src, out_pdf)
        if ok:
            ok_files.append(src.name)
        else:
            bad_files.append((src.name, msg))

    return ok_files, bad_files