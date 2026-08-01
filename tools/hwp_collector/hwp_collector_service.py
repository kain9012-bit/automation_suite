from __future__ import annotations

from pathlib import Path

import pythoncom
import win32com.client

SUPPORTED_EXTS = {".hwp", ".hwpx"}


def is_supported_hanfile(p: Path) -> bool:
    return p.is_file() and p.suffix.lower() in SUPPORTED_EXTS


def list_han_files_in_folder(folder: Path) -> list[Path]:
    return sorted([p.resolve() for p in folder.iterdir() if is_supported_hanfile(p)])


def get_hwp_object():
    prog_ids = [
        "HWPFrame.HwpObject",
        "HwpFrame.HwpObject",
        "HWPFrame.HwpObject.1",
        "HwpFrame.HwpObject.1",
    ]
    last_err = None
    for pid in prog_ids:
        try:
            return win32com.client.Dispatch(pid)
        except Exception as e:
            last_err = e

    raise RuntimeError(
        "한글(HWP) COM 객체를 생성할 수 없습니다.\n"
        "한글 설치 상태 및 COM 동작 여부를 확인해 주세요.\n\n"
        f"내부 오류: {last_err}"
    )


def run_action(hwp, name):
    try:
        hwp.HAction.Run(name)
        return True
    except Exception:
        return False


def action_file_new(hwp):
    if run_action(hwp, "FileNew"):
        return
    if run_action(hwp, "New"):
        return
    raise RuntimeError("새 문서 생성(FileNew)에 실패했습니다.")


def action_move_end(hwp):
    if run_action(hwp, "MoveDocEnd"):
        return
    if run_action(hwp, "MoveEndDoc"):
        return
    try:
        hwp.MovePos(3)
        return
    except Exception as e:
        raise RuntimeError(f"문서 끝 이동에 실패했습니다.\n\n{e}")


def action_page_break(hwp):
    run_action(hwp, "BreakPage")


def action_insert_file(hwp, path: str, keep_section: int = 0):
    try:
        ps = hwp.HParameterSet.HInsertFile
        hwp.HAction.GetDefault("InsertFile", ps.HSet)

        set_ok = False
        for f in ["FileName", "Filename", "FullName", "Path", "Name"]:
            try:
                setattr(ps, f, path)
                set_ok = True
                break
            except Exception:
                continue
        if not set_ok:
            raise RuntimeError("파일 삽입 파라미터에 경로를 설정할 수 없습니다.")

        try:
            ps.KeepSection = keep_section
        except Exception:
            pass

        hwp.HAction.Execute("InsertFile", ps.HSet)
        return
    except Exception as e:
        raise RuntimeError(f"파일 삽입(InsertFile)에 실패했습니다:\n{path}\n\n{e}")


def action_file_save_as(hwp, path: str):
    try:
        hwp.SaveAs(path)
        return
    except Exception:
        pass

    try:
        hwp.SaveAs(path, "HWP")
        return
    except Exception:
        pass

    try:
        ps = hwp.HParameterSet.HFileSaveAs
        hwp.HAction.GetDefault("FileSaveAs", ps.HSet)

        ps.SaveFileName = path
        try:
            ps.SaveOverWrite = 1
        except Exception:
            pass
        try:
            ps.SaveFormat = "HWP"
        except Exception:
            pass

        hwp.HAction.Execute("FileSaveAs", ps.HSet)
        return
    except Exception as e:
        raise RuntimeError(f"저장(FileSaveAs)에 실패했습니다:\n{path}\n\n{e}")


def merge_han_files(file_paths: list[Path], output_path: str | Path):
    if not file_paths:
        raise ValueError("취합할 파일이 없습니다.")

    pythoncom.CoInitialize()
    hwp = get_hwp_object()

    try:
        try:
            hwp.RegisterModule("FilePathCheckDLL", "SecurityModule")
        except Exception:
            pass

        ordered = [Path(p).resolve() for p in file_paths if Path(p).exists() and Path(p).suffix.lower() in SUPPORTED_EXTS]
        if not ordered:
            raise ValueError("취합할 파일이 없습니다(존재하는 파일이 없음).")

        action_file_new(hwp)

        inserted_any = False
        for fp in ordered:
            fp_str = str(fp)

            if inserted_any:
                action_move_end(hwp)
                action_page_break(hwp)
                action_move_end(hwp)
            else:
                action_move_end(hwp)

            action_insert_file(hwp, fp_str, keep_section=0)
            inserted_any = True

        action_file_save_as(hwp, str(Path(output_path).resolve()))

    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass