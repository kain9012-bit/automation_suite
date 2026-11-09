from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


SUPPORTED_EXT = ".hwp"
LogCallback = Callable[[str], None]
StatusCallback = Callable[[Path, str], None]
CancelCheck = Callable[[], bool]

ALLOW_HINT = "한글이 파일 접근을 물으면 [허용]을 눌러 주세요."

# 한글(Hwp.exe)이 꺼졌거나 연결이 끊겼을 때 COM 이 내는 오류 번호. 이 오류가 나면 그 한글로는
# 더 할 수 있는 것이 없어 새로 띄워야 한다. 1.4.8까지는 한 번 띄운 한글로 끝까지 해서, 첫 파일을
# 저장하다 한글이 꺼지자 나머지 275개가 모두 'RPC 서버를 사용할 수 없습니다'로 열기 실패했다.
HWP_GONE_HRESULTS = (
    -2147023174,  # 0x800706BA RPC 서버를 사용할 수 없습니다.
    -2147023170,  # 0x800706BE 원격 프로시저 호출에 실패했습니다.
    -2147023169,  # 0x800706BF 원격 프로시저 호출에 실패했으며 실행되지 않았습니다.
    -2147417848,  # 0x80010108 개체가 해당 클라이언트에서 연결이 끊어졌습니다.
)


@dataclass
class HwpToHwpxResult:
    source_path: Path
    output_path: Path
    success: bool
    deleted_original: bool = False
    overwritten: bool = False
    error: str = ""


@dataclass
class HwpToHwpxBatchResult:
    success_count: int = 0
    delete_fail_count: int = 0
    fail_count: int = 0
    overwrite_count: int = 0
    renamed_count: int = 0  # 같은 이름의 HWPX 가 있어 '이름(1).hwpx' 처럼 번호를 붙여 저장한 수
    stopped: bool = False
    results: list[HwpToHwpxResult] = field(default_factory=list)


def normalize_path(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def is_office_temp_file(path: str | Path) -> bool:
    name = Path(path).name
    return name.startswith("~$") or name.startswith(".~")


def is_hwp_file(path: str | Path) -> bool:
    file_path = Path(path)
    if not file_path.is_file():
        return False
    if is_office_temp_file(file_path):
        return False
    name = file_path.name.lower()
    return name.endswith(SUPPORTED_EXT) and not name.endswith(".hwpx")


def collect_hwp_files_from_folder(folder_path: str | Path, recursive: bool = True) -> list[Path]:
    folder = Path(folder_path)
    result: list[Path] = []
    if not folder.is_dir():
        return result

    if recursive:
        for current, _, files in os.walk(folder):
            current_path = Path(current)
            for filename in files:
                path = current_path / filename
                if is_hwp_file(path):
                    result.append(path.resolve())
    else:
        for path in folder.iterdir():
            if is_hwp_file(path):
                result.append(path.resolve())

    return sorted(result, key=normalize_path)


def output_hwpx_path(src_path: str | Path) -> Path:
    src = Path(src_path).resolve()
    return src.with_suffix(".hwpx")


def ensure_pywin32_available() -> None:
    try:
        import pythoncom  # noqa: F401
        import win32com.client  # noqa: F401
    except Exception as exc:
        raise RuntimeError(
            "pywin32가 설치되어 있지 않습니다.\n"
            "PowerShell에서 다음 명령을 먼저 실행해 주세요.\n\n"
            "python -m pip install pywin32"
        ) from exc


def try_register_file_path_security_module(hwp):
    module_names = [
        os.environ.get("HWP_FILE_PATH_CHECKER_MODULE", "").strip(),
        "SecurityModule",
        "FilePathCheckerModule",
        "FilePathCheckerModuleExample",
    ]

    tried: set[str] = set()
    last_error = ""

    for module_name in module_names:
        if not module_name or module_name in tried:
            continue
        tried.add(module_name)

        try:
            result = hwp.RegisterModule("FilePathCheckDLL", module_name)
            if bool(result):
                return True, module_name, ""
            last_error = f"RegisterModule 반환값이 False 또는 빈 값입니다: {module_name}"
        except Exception as exc:
            last_error = f"{module_name}: {exc}"

    return False, "", last_error


def is_hwp_gone_error(exc: BaseException | None) -> bool:
    """한글이 꺼졌거나 연결이 끊겨 난 오류인지. open_hwp·save_as_hwpx 는 COM 오류를 글로 묶어
    다시 내므로 번호가 글 안에 있는지도 본다."""
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        args = getattr(exc, "args", ())
        if args and isinstance(args[0], int) and args[0] in HWP_GONE_HRESULTS:
            return True
        text = str(exc).upper()
        for code in HWP_GONE_HRESULTS:
            if str(code) in text or f"0X{code & 0xFFFFFFFF:08X}" in text:
                return True
        exc = exc.__cause__ or exc.__context__
    return False


def create_hwp_object(visible: bool = False):
    # 늦은 바인딩(dynamic)만 쓴다. gencache.EnsureDispatch 는 임시 폴더(gen_py)에 한글
    # 기능 목록 캐시를 만들고, 그 캐시가 망가지면 이 도구뿐 아니라 한글을 쓰는 다른 도구도
    # "has no attribute 'CLSIDToPackageMap'" 로 멈춘다.
    import win32com.client.dynamic

    hwp = None
    errors: list[str] = []
    for prog_id in ("HWPFrame.HwpObject", "HwpFrame.HwpObject", "HWPFrame.HwpObject.1"):
        try:
            hwp = win32com.client.dynamic.Dispatch(prog_id)
            break
        except Exception as exc:
            errors.append(str(exc))

    if hwp is None:
        raise RuntimeError(
            "한글(HWP) COM 객체를 생성할 수 없습니다.\n"
            "한글 설치 상태 및 COM 동작 여부를 확인해 주세요.\n\n"
            "내부 오류:\n" + "\n".join(errors[-3:])
        )

    try:
        security_ok, security_module_name, security_error = try_register_file_path_security_module(hwp)

        # 보안 모듈이 없으면 한글이 '접근 허용' 창을 띄운다. 창을 숨기면 그 창도 안 보여
        # 누를 수 없고 변환이 끝나지 않으므로, 그때는 한글 창을 보여 준다.
        try:
            hwp.XHwpWindows.Item(0).Visible = bool(visible) or not security_ok
        except Exception:
            pass
    except BaseException:
        # 한글을 띄운 뒤 실패하면 여기서 끄지 않으면 숨은 Hwp.exe 가 남는다.
        quit_hwp(hwp)
        raise

    return hwp, security_ok, security_module_name, security_error


def quit_hwp(hwp) -> None:
    if hwp is None:
        return
    try:
        hwp.Clear(1)
    except Exception:
        pass
    try:
        hwp.Quit()
    except Exception:
        pass


def close_current_hwp_document(hwp) -> None:
    try:
        hwp.Clear(1)
        return
    except Exception:
        pass

    try:
        hwp.HAction.Run("FileClose")
        return
    except Exception:
        pass

    try:
        hwp.HAction.GetDefault("FileClose", hwp.HParameterSet.HFileOpenSave.HSet)
        hwp.HAction.Execute("FileClose", hwp.HParameterSet.HFileOpenSave.HSet)
    except Exception:
        pass


def open_hwp(hwp, src_path: str) -> None:
    errors: list[str] = []
    attempts = [
        ("", ""),
        ("HWP", ""),
        ("HWP", "forceopen:true"),
        ("", "forceopen:true"),
    ]

    for file_format, option in attempts:
        try:
            result = hwp.Open(src_path, file_format, option)
            if result is False:
                errors.append(f"Open 반환값 False / format={file_format}, option={option}")
                continue
            return
        except Exception as exc:
            errors.append(str(exc))

    raise RuntimeError("HWP 파일 열기 실패: " + " | ".join(errors[-2:]))


def save_as_hwpx(hwp, dst_path: str) -> None:
    errors: list[str] = []

    for file_format in ("HWPX", "HWPXDocument", "HWPX File"):
        try:
            hwp.SaveAs(dst_path, file_format, "")
            if os.path.exists(dst_path) and os.path.getsize(dst_path) > 0:
                return
        except Exception as exc:
            errors.append(f"SaveAs({file_format}) 실패: {exc}")

    try:
        hwp.HAction.GetDefault("FileSaveAs_S", hwp.HParameterSet.HFileOpenSave.HSet)
        hwp.HParameterSet.HFileOpenSave.filename = dst_path
        hwp.HParameterSet.HFileOpenSave.Format = "HWPX"
        hwp.HParameterSet.HFileOpenSave.Attributes = 0
        hwp.HAction.Execute("FileSaveAs_S", hwp.HParameterSet.HFileOpenSave.HSet)
        if os.path.exists(dst_path) and os.path.getsize(dst_path) > 0:
            return
    except Exception as exc:
        errors.append(f"FileSaveAs_S 실패: {exc}")

    raise RuntimeError("HWPX 저장 실패: " + " | ".join(errors[-3:]))


def safe_temp_name(ext: str) -> str:
    ext = (ext or "").lower()
    if not ext.startswith("."):
        ext = "." + ext
    return "input" + ext


def replace_file(src_file: Path, dst_file: Path) -> None:
    dst_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        os.replace(str(src_file), str(dst_file))
        return
    except Exception:
        pass

    if dst_file.exists():
        try:
            dst_file.unlink()
        except Exception:
            pass
    shutil.copy2(str(src_file), str(dst_file))


def convert_hwp_to_hwpx_via_temp(hwp, src_path: str | Path, dst_path: str | Path) -> None:
    src = Path(src_path).resolve()
    dst = Path(dst_path).resolve()
    temp_dir = Path(tempfile.mkdtemp(prefix="hwp2hwpx_"))
    opened = False

    try:
        tmp_in = temp_dir / safe_temp_name(src.suffix.lower() or ".hwp")
        tmp_out = temp_dir / "output.hwpx"

        shutil.copy2(str(src), str(tmp_in))
        open_hwp(hwp, str(tmp_in))
        opened = True
        save_as_hwpx(hwp, str(tmp_out))

        if not tmp_out.exists() or tmp_out.stat().st_size == 0:
            raise RuntimeError("HWPX 파일이 생성되지 않았습니다.")

        replace_file(tmp_out, dst)
    finally:
        if opened:
            try:
                close_current_hwp_document(hwp)
            except Exception:
                pass
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass


def delete_original_hwp(src_path: str | Path) -> tuple[bool, str]:
    try:
        os.remove(src_path)
        return True, ""
    except PermissionError as exc:
        try:
            os.chmod(src_path, 0o666)
            os.remove(src_path)
            return True, ""
        except Exception as retry_exc:
            return False, f"원본 삭제 실패: {retry_exc or exc}"
    except Exception as exc:
        return False, f"원본 삭제 실패: {exc}"


def convert_hwp_files_to_hwpx(
    file_paths: list[Path],
    visible: bool = False,
    log: LogCallback | None = None,
    status: StatusCallback | None = None,
    cancel: CancelCheck | None = None,
) -> HwpToHwpxBatchResult:
    def emit(message: str = "") -> None:
        if log is not None:
            log(message)

    def cancelled() -> bool:
        try:
            return bool(cancel and cancel())
        except Exception:
            return False

    def set_status(path: Path, text: str) -> None:
        if status is not None:
            status(path, text)

    ensure_pywin32_available()
    import pythoncom

    ordered = [Path(path).resolve() for path in file_paths if is_hwp_file(path)]
    if not ordered:
        raise ValueError("변환할 HWP 파일이 없습니다.")

    batch = HwpToHwpxBatchResult()
    pythoncom.CoInitialize()
    hwp = None
    restart_error = ""  # 한글을 다시 띄우지 못했으면 그 까닭. 남은 파일은 열지 않고 이 까닭으로 실패.

    def start_new_hwp() -> None:
        """꺼진 한글을 놓고 새로 띄운다. 못 띄우면 restart_error 를 남기고 RuntimeError."""
        nonlocal hwp, restart_error
        quit_hwp(hwp)  # 꺼진 한글이면 아무 일 없이 넘어간다.
        hwp = None
        try:
            new_hwp, new_security_ok, _name, _error = create_hwp_object(visible=visible)
        except Exception as exc:
            first_line = (str(exc).strip().splitlines() or [""])[0]
            restart_error = f"한글을 다시 띄우지 못했습니다: {first_line}"
            raise RuntimeError(restart_error) from exc
        hwp = new_hwp
        if not new_security_ok:
            emit(f"  - {ALLOW_HINT}")

    emit("===== HWP → HWPX 변환 시작 =====")
    emit(f"처리 대상 파일: {len(ordered)}개")
    emit("저장 방식: 원본과 같은 폴더에 같은 이름의 HWPX 생성")
    emit("원본 처리: 변환 성공 시 HWP 삭제")
    emit("기존 HWPX 처리: 같은 이름이 있으면 덮어쓰지 않고 '이름(1).hwpx'처럼 번호를 붙여 저장")
    emit(f"한글 창 보이기: {'예' if visible else '아니오'}")

    try:
        hwp, security_ok, security_module_name, security_error = create_hwp_object(visible=visible)
        if security_ok:
            emit(f"보안모듈 등록: 성공({security_module_name})")
        else:
            emit("보안모듈 등록: 실패 또는 미등록")
            if security_error:
                emit(f"  - 사유: {security_error}")
            emit(f"  - {ALLOW_HINT}")
        emit()

        for index, src_path in enumerate(ordered, start=1):
            if cancelled():
                batch.stopped = True
                emit("중지했습니다. 그때까지 바꾼 파일은 그대로 둡니다.")
                break
            # 같은 이름의 HWPX 가 이미 있으면 덮어쓰지 않고 '이름(1).hwpx' 로 저장한다.
            dst_path = output_hwpx_path(src_path)
            renamed = dst_path.exists()
            if renamed:
                # 번호 변수를 따로 둔다. index 를 다시 쓰면 아래 [번호/전체] 안내가 틀어진다.
                number = 1
                while (dst_path.parent / f"{dst_path.stem}({number}).hwpx").exists():
                    number += 1
                dst_path = dst_path.parent / f"{dst_path.stem}({number}).hwpx"
            overwritten = False

            set_status(src_path, "변환 중")
            emit(f"[{index}/{len(ordered)}] {src_path.name}")
            emit(f"  - 원본 HWP: {src_path}")
            emit(f"  - 변환 HWPX: {dst_path}")
            if renamed:
                emit(f"  - 안내: 같은 이름의 HWPX가 있어 {dst_path.name} 로 저장합니다.")

            try:
                if restart_error:
                    raise RuntimeError(restart_error)
                if hwp is None:
                    # 앞 파일을 변환하다 한글이 꺼졌다.
                    start_new_hwp()
                    emit("  - 앞 파일에서 한글이 꺼져 다시 띄웠습니다.")
                try:
                    convert_hwp_to_hwpx_via_temp(hwp, src_path, dst_path)
                except Exception as exc:
                    if not is_hwp_gone_error(exc):
                        raise
                    start_new_hwp()
                    emit("  - 한글이 응답하지 않아 다시 띄웠습니다. 이 파일을 한 번 더 변환합니다.")
                    try:
                        convert_hwp_to_hwpx_via_temp(hwp, src_path, dst_path)
                    except Exception as retry_exc:
                        if not is_hwp_gone_error(retry_exc):
                            raise
                        # 다시 해도 꺼졌다. 이 파일만 실패로 두고 다음 파일은 새 한글로 한다.
                        quit_hwp(hwp)
                        hwp = None
                        raise RuntimeError(
                            f"이 파일을 변환하는 중 한글이 두 번 꺼졌습니다: {retry_exc}"
                        ) from retry_exc
                if not dst_path.exists() or dst_path.stat().st_size == 0:
                    raise RuntimeError("변환된 HWPX 파일을 확인할 수 없습니다.")
                if renamed:
                    batch.renamed_count += 1

                delete_ok, delete_msg = delete_original_hwp(src_path)
                if delete_ok:
                    batch.success_count += 1
                    if overwritten:
                        batch.overwrite_count += 1
                    set_status(src_path, "완료")
                    emit("  - 결과: 변환 완료, 원본 HWP 삭제 완료")
                    batch.results.append(
                        HwpToHwpxResult(
                            source_path=src_path,
                            output_path=dst_path,
                            success=True,
                            deleted_original=True,
                            overwritten=overwritten,
                        )
                    )
                else:
                    batch.delete_fail_count += 1
                    set_status(src_path, "삭제 실패")
                    emit(f"  - 결과: 변환 완료, {delete_msg}")
                    batch.results.append(
                        HwpToHwpxResult(
                            source_path=src_path,
                            output_path=dst_path,
                            success=True,
                            deleted_original=False,
                            overwritten=overwritten,
                            error=delete_msg,
                        )
                    )
            except Exception as exc:
                batch.fail_count += 1
                set_status(src_path, "실패")
                emit(f"  ! 변환 실패: {exc}")
                emit("  - 원본 HWP는 삭제하지 않았습니다.")
                batch.results.append(
                    HwpToHwpxResult(
                        source_path=src_path,
                        output_path=dst_path,
                        success=False,
                        overwritten=overwritten,
                        error=str(exc),
                    )
                )
            emit()
    finally:
        try:
            quit_hwp(hwp)
        finally:
            # CoUninitialize 보다 먼저 한글 연결을 놓아야 한다.
            hwp = None
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass

    emit("===== 완료 =====")
    emit(f"성공: {batch.success_count}개")
    emit(f"원본 삭제 실패: {batch.delete_fail_count}개")
    emit(f"변환 실패: {batch.fail_count}개")
    emit(f"같은 이름이 있어 번호를 붙여 저장: {batch.renamed_count}개")
    return batch
