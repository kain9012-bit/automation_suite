from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Callable, Tuple

import pythoncom
import win32com.client
import win32com.client.dynamic


SUPPORTED_EXTS = {".hwp", ".hwpx"}

ProgressCallback = Callable[[str], None]
CancelCheck = Callable[[], bool]

ALLOW_HINT = "한글이 파일 접근을 물으면 [허용]을 눌러 주세요."


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


def get_hwp_object():
    """한글을 늦은 바인딩(dynamic)으로 부른다.

    win32com.client.Dispatch 는 임시 폴더(gen_py)의 한글 기능 목록 캐시를 믿고 쓰는데,
    그 캐시가 망가진 PC 에서는 "has no attribute 'CLSIDToPackageMap'" 로 한글을 부르지도
    못한다. 늦은 바인딩은 캐시를 쓰지 않는다(한글 파일 취합과 같은 방식).
    """
    errors = []
    for pid in ("HWPFrame.HwpObject", "HwpFrame.HwpObject", "HWPFrame.HwpObject.1"):
        try:
            return win32com.client.dynamic.Dispatch(pid)
        except Exception as e:
            errors.append(str(e))
    raise RuntimeError(
        "한글(HWP) COM 객체를 생성할 수 없습니다. 한글 설치 상태를 확인해 주세요. "
        f"(내부 오류: {errors[-1] if errors else ''})"
    )


def register_security_module(hwp) -> bool:
    """한글이 파일 접근 허락 창을 띄우지 않게 하는 보안 모듈. 설치 방식마다 이름이 달라
    여러 개를 시도한다. 하나도 등록되지 않으면 False."""
    names = [
        os.environ.get("HWP_FILE_PATH_CHECKER_MODULE", "").strip(),
        "SecurityModule",
        "FilePathCheckerModule",
        "FilePathCheckerModuleExample",
    ]
    tried = set()
    for name in names:
        if not name or name in tried:
            continue
        tried.add(name)
        try:
            if hwp.RegisterModule("FilePathCheckDLL", name):
                return True
        except Exception:
            continue
    return False


def _open_document(hwp, path: str) -> None:
    """문서를 연다. 열지 못하면 예외. Open 이 False 를 돌려주거나 문서가 비어 있으면
    한글은 처음 빈 문서를 그대로 들고 있어, 그대로 저장하면 빈 PDF 가 나온다."""
    try:
        result = hwp.Open(path, "", "")
    except Exception:
        result = hwp.Open(path)
    if result is not None and not result:
        raise RuntimeError("한글에서 파일을 열지 못했습니다.")
    try:
        opened_path = hwp.Path
    except Exception:
        opened_path = None
    if isinstance(opened_path, str) and not opened_path.strip():
        raise RuntimeError("한글에서 파일을 열지 못했습니다(빈 문서).")


def convert_with_hancom(
    input_path: Path,
    output_path: Path,
    progress: ProgressCallback | None = None,
) -> Tuple[bool, str]:
    input_path = Path(input_path).resolve()
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pythoncom.CoInitialize()
    hwp = None
    temp_dir = None

    try:
        hwp = get_hwp_object()

        security_ok = register_security_module(hwp)

        # 보안 모듈이 없으면 한글이 '접근 허용' 창을 띄운다. 창을 숨기면 그 창도 안 보여
        # 누를 수 없고 변환이 끝나지 않으므로, 그때는 한글 창을 보여 준다.
        try:
            hwp.XHwpWindows.Item(0).Visible = not security_ok
        except Exception:
            pass
        if not security_ok and progress is not None:
            try:
                progress(ALLOW_HINT)
            except Exception:
                pass

        # 원본 프로그램처럼 임시폴더에 복사해서 열기
        temp_dir = Path(tempfile.mkdtemp(prefix="hwp2pdf_"))
        ext = input_path.suffix.lower()
        tmp_in = temp_dir / _safe_temp_name(ext)
        tmp_out = temp_dir / "output.pdf"

        shutil.copy2(str(input_path), str(tmp_in))

        try:
            _open_document(hwp, str(tmp_in))
        except Exception as e:
            return False, str(e)

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
            # CoUninitialize 보다 먼저 한글 연결을 놓아야 한다.
            hwp = None
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
    """같은 이름의 PDF 가 이미 있으면 덮어쓰지 않고 '이름(1).pdf' 로 만든다."""
    base = safe_basename(src.stem)
    path = output_dir / f"{base}.pdf"
    index = 1
    while path.exists():
        path = output_dir / f"{base}({index}).pdf"
        index += 1
    return path


def convert_files(
    file_paths: list[Path],
    output_dir: Path,
    progress: ProgressCallback | None = None,
    cancel: CancelCheck | None = None,
) -> tuple[list[str], list[tuple[str, str]]]:
    """파일마다 PDF 로 바꾼다. 중지 신호가 오면 하던 파일까지 마치고 멈춘다
    (그때는 성공+실패 수가 입력 수보다 적다)."""
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    ok_files: list[str] = []
    bad_files: list[tuple[str, str]] = []
    hinted = False

    def emit(text: str) -> None:
        nonlocal hinted
        if progress is None:
            return
        if text == ALLOW_HINT:
            # 파일마다 한글을 새로 띄우므로 같은 안내가 반복된다. 한 번만 알린다.
            if hinted:
                return
            hinted = True
        try:
            progress(text)
        except Exception:
            pass

    for index, src in enumerate(file_paths, start=1):
        try:
            if cancel is not None and cancel():
                emit("중지했습니다. 그때까지 바꾼 파일은 그대로 둡니다.")
                break
        except Exception:
            pass

        src = Path(src).resolve()

        if not src.exists():
            bad_files.append((src.name, "파일이 존재하지 않습니다."))
            continue

        if src.suffix.lower() not in SUPPORTED_EXTS:
            bad_files.append((src.name, "지원하지 않는 확장자입니다."))
            continue

        if len(file_paths) > 1:
            emit(f"[{index}/{len(file_paths)}] {src.name}")
        out_pdf = build_output_pdf_path(src, output_dir)
        ok, msg = convert_with_hancom(src, out_pdf, progress=emit)
        if ok:
            ok_files.append(src.name)
        else:
            bad_files.append((src.name, msg))
            emit(f"{src.name}: 변환하지 못했습니다 ({msg})")

    return ok_files, bad_files
