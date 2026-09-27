from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

import pythoncom
import win32com.client
import win32com.client.dynamic

SUPPORTED_EXTS = {".hwp", ".hwpx"}

ProgressCallback = Callable[[str], None]
CancelCheck = Callable[[], bool]

ALLOW_HINT = "한글이 파일 접근을 물으면 [허용]을 눌러 주세요."


def is_supported_hanfile(p: Path) -> bool:
    return p.is_file() and p.suffix.lower() in SUPPORTED_EXTS


def list_han_files_in_folder(folder: Path) -> list[Path]:
    return sorted([p.resolve() for p in folder.iterdir() if is_supported_hanfile(p)])


def get_hwp_object():
    """한글을 늦은 바인딩(dynamic)으로 부른다.

    win32com.client.Dispatch 는 임시 폴더(AppData/Local/Temp/gen_py)에 남은 한글 기능 목록
    캐시가 있으면 그것을 믿고 쓴다. 그 캐시는 PC마다 따로 만들어지고(HWP→HWPX 변환 등이
    gencache 로 만든다), 일부 파일이 지워지면 "has no attribute 'CLSIDToPackageMap'" 처럼
    한글을 부르지도 못하고 멈춘다. 캐시를 쓰지 않고 한글에게 직접 묻는 방식이면 캐시가
    없든, 있든, 망가졌든 똑같이 동작한다. 늦은 바인딩은 속성 이름의 대소문자도 가리지 않는다.
    """
    prog_ids = [
        "HWPFrame.HwpObject",
        "HwpFrame.HwpObject",
        "HWPFrame.HwpObject.1",
        "HwpFrame.HwpObject.1",
    ]
    last_err = None
    for pid in prog_ids:
        try:
            return win32com.client.dynamic.Dispatch(pid)
        except Exception as e:
            last_err = e

    raise RuntimeError(
        "한글(HWP) COM 객체를 생성할 수 없습니다.\n"
        "한글 설치 상태 및 COM 동작 여부를 확인해 주세요.\n\n"
        f"내부 오류: {last_err}"
    )


def register_security_module(hwp) -> bool:
    """한글이 파일 접근 허락 창을 띄우지 않게 하는 보안 모듈을 등록한다.

    설치 방식(한글 2018~2024, 보안 모듈 설치 여부)마다 이름이 달라 여러 개를 시도한다.
    하나도 등록되지 않으면 False. 그때는 한글이 파일마다 '접근 허용' 창을 띄운다.
    """
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


def show_hwp_window(hwp) -> None:
    """보안 모듈이 없으면 한글 창을 보여 준다. 숨긴 채로 두면 '접근 허용' 창도 안 보여
    누를 사람이 없고, 작업이 끝나지 않은 채 멈춘다."""
    try:
        hwp.XHwpWindows.Item(0).Visible = True
    except Exception:
        pass


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


def action_page_break(hwp) -> bool:
    return run_action(hwp, "BreakPage")


def _set_param_path(ps, path: str):
    """파라미터 개체에 파일 경로를 넣는다. 넣었으면 (True, 시도기록, 가진이름들).

    타입 라이브러리로 만들어진 개체(이른 바인딩)는 속성 이름의 대소문자를 가린다.
    같은 한글이라도 늦은 바인딩이면 안 가린다. 실습장에서는 되고 다른 PC에서는
    안 되던 것이 이 차이 때문이었다. 그래서 이름을 찍어 맞추지 않고, 개체가
    실제로 가진 이름을 읽어 대소문자를 무시하고 고른다.
    """
    available = []
    try:
        available.extend(getattr(ps, "_prop_map_put_", {}).keys())
    except Exception:
        pass
    if not available:
        try:
            available = [n for n in dir(ps) if not n.startswith("_")]
        except Exception:
            available = []

    lookup = {}
    for name in available:
        lookup.setdefault(name.lower(), name)

    order = []
    for want in ("filename", "fullname", "path", "name"):
        real = lookup.get(want)
        if real and real not in order:
            order.append(real)
    # 이름 목록을 못 읽었을 때를 위해 흔한 표기도 뒤에 붙인다.
    for fallback in ("filename", "FileName", "Filename", "FullName", "Path", "Name"):
        if fallback not in order:
            order.append(fallback)

    tried = []
    for name in order:
        try:
            setattr(ps, name, path)
            return True, tried, available
        except Exception as error:
            tried.append(f"{name}: {type(error).__name__}: {error}")

    return False, tried, available


def action_insert_file(hwp, path: str, keep_section: int = 0):
    try:
        ps = hwp.HParameterSet.HInsertFile
        hwp.HAction.GetDefault("InsertFile", ps.HSet)

        set_ok, tried, available = _set_param_path(ps, path)
        if not set_ok:
            detail = "\n".join("  - " + line for line in tried)
            names = ", ".join(sorted(available)) if available else "(이름을 읽지 못함)"
            raise RuntimeError(
                "파일 삽입 파라미터에 경로를 설정할 수 없습니다.\n"
                f"파라미터 개체가 가진 이름: {names}\n"
                "시도한 이름과 실제 오류:\n" + detail
            )

        try:
            ps.KeepSection = keep_section
        except Exception:
            pass

        result = hwp.HAction.Execute("InsertFile", ps.HSet)
    except Exception as e:
        raise RuntimeError(f"파일 삽입(InsertFile)에 실패했습니다:\n{path}\n\n{e}")
    # Execute 는 실패하면 예외 없이 False 를 돌려준다. 이것을 보지 않으면 그 파일만
    # 조용히 빠진 채 취합이 끝난다.
    if result is not None and not result:
        raise RuntimeError("한글이 이 파일을 끼워 넣지 못했습니다.")


def save_format_for(path: str) -> str:
    """저장 확장자에 맞는 한글 저장 형식. .hwpx 에 HWP(이진) 형식을 넣으면 열리지 않는다."""
    return "HWPX" if Path(path).suffix.lower() == ".hwpx" else "HWP"


def _saved_ok(path: str, file_format: str) -> bool:
    try:
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            return False
        if file_format == "HWPX":
            # hwpx 는 ZIP 이다. 앞 두 글자가 PK 가 아니면 속이 HWP 이진 형식이다.
            with open(path, "rb") as f:
                return f.read(2) == b"PK"
        return True
    except OSError:
        return False


def action_file_save_as(hwp, path: str):
    file_format = save_format_for(path)
    errors = []

    for args in ((path, file_format, ""), (path, file_format)):
        try:
            result = hwp.SaveAs(*args)
            if result is not None and not result:
                errors.append(f"SaveAs({file_format}) 반환값 False")
                continue
            if _saved_ok(path, file_format):
                return
            errors.append(f"SaveAs({file_format}) 뒤 {file_format} 파일을 확인하지 못함")
        except Exception as e:
            errors.append(f"SaveAs({file_format}): {e}")

    try:
        ps = hwp.HParameterSet.HFileOpenSave
        hwp.HAction.GetDefault("FileSaveAs_S", ps.HSet)
        ps.filename = path
        ps.Format = file_format
        try:
            ps.Attributes = 0
        except Exception:
            pass
        hwp.HAction.Execute("FileSaveAs_S", ps.HSet)
        if _saved_ok(path, file_format):
            return
        errors.append(f"FileSaveAs_S({file_format}) 뒤 {file_format} 파일을 확인하지 못함")
    except Exception as e:
        errors.append(f"FileSaveAs_S({file_format}): {e}")

    raise RuntimeError(f"저장(FileSaveAs)에 실패했습니다:\n{path}\n\n" + "\n".join(errors[-3:]))


def merge_han_files(
    file_paths: list[Path],
    output_path: str | Path,
    progress: ProgressCallback | None = None,
    cancel: CancelCheck | None = None,
) -> dict:
    """한글 파일들을 차례로 한 문서에 끼워 넣어 output_path 로 저장한다.

    돌려주는 값: {"inserted": [파일 이름], "failed": [{"name", "error"}],
    "stopped": 중지했는지, "saved": 결과 파일을 저장했는지}.
    끼워 넣지 못한 파일은 failed 에 넣고 나머지로 계속한다.
    """

    def emit(text: str) -> None:
        if progress is not None:
            try:
                progress(text)
            except Exception:
                pass

    def cancelled() -> bool:
        try:
            return bool(cancel and cancel())
        except Exception:
            return False

    if not file_paths:
        raise ValueError("취합할 파일이 없습니다.")

    ordered = [Path(p).resolve() for p in file_paths if Path(p).exists() and Path(p).suffix.lower() in SUPPORTED_EXTS]
    if not ordered:
        raise ValueError("취합할 파일이 없습니다(존재하는 파일이 없음).")

    inserted: list[str] = []
    failed: list[dict] = []
    stopped = False
    saved = False

    pythoncom.CoInitialize()
    hwp = None

    try:
        hwp = get_hwp_object()

        if not register_security_module(hwp):
            show_hwp_window(hwp)
            emit(ALLOW_HINT)

        action_file_new(hwp)

        for index, fp in enumerate(ordered, start=1):
            if cancelled():
                stopped = True
                break
            fp_str = str(fp)
            if len(ordered) > 1:
                emit(f"[{index}/{len(ordered)}] {fp.name}")

            broke_page = False
            if inserted:
                action_move_end(hwp)
                broke_page = action_page_break(hwp)
                action_move_end(hwp)
            else:
                action_move_end(hwp)

            try:
                action_insert_file(hwp, fp_str, keep_section=0)
            except Exception as e:
                reason = str(e).strip().splitlines()[-1] if str(e).strip() else type(e).__name__
                failed.append({"name": fp.name, "error": reason})
                emit(f"{fp.name}: 넣지 못했습니다 ({reason})")
                # 이 파일 앞에 넣은 쪽 나누기를 되돌려 빈 쪽이 남지 않게 한다.
                if broke_page:
                    action_move_end(hwp)
                    run_action(hwp, "DeleteBack")
                continue
            inserted.append(fp.name)

        if stopped:
            emit("중지했습니다. 그때까지 넣은 파일만 저장합니다." if inserted else "중지했습니다.")

        if not inserted:
            if stopped:
                return {"inserted": inserted, "failed": failed, "stopped": True, "saved": False}
            raise RuntimeError(
                "취합할 수 있는 파일이 없었습니다.\n\n"
                + "\n".join(f"· {item['name']}: {item['error']}" for item in failed)
            )

        action_file_save_as(hwp, str(Path(output_path).resolve()))
        saved = True
        return {"inserted": inserted, "failed": failed, "stopped": stopped, "saved": saved}

    finally:
        # 한글은 COM으로 띄우면 이 함수가 끝나도 프로세스가 살아남는다. 그러면
        # 취합에 쓴 파일을 계속 붙잡아, 작업이 끝난 뒤에도 그 파일을 지울 수 없다.
        # CoUninitialize() 는 이쪽 연결만 끊을 뿐 한글을 끄지 않는다.
        # Clear(1) 로 저장 여부를 묻지 않고 문서를 비운 뒤 Quit() 으로 끝낸다.
        # 다형식 PDF 통합의 convert_with_hancom 이 쓰는 것과 같은 방식이다.
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
