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


def create_hwp_object(visible: bool = False):
    import win32com.client
    import win32com.client.dynamic

    attempts = [
        lambda: win32com.client.gencache.EnsureDispatch("HWPFrame.HwpObject"),
        lambda: win32com.client.Dispatch("HWPFrame.HwpObject"),
        lambda: win32com.client.dynamic.Dispatch("HWPFrame.HwpObject"),
    ]

    hwp = None
    errors: list[str] = []
    for attempt in attempts:
        try:
            hwp = attempt()
            break
        except Exception as exc:
            errors.append(str(exc))

    if hwp is None:
        raise RuntimeError(
            "한글(HWP) COM 객체를 생성할 수 없습니다.\n"
            "한글 설치 상태 및 COM 동작 여부를 확인해 주세요.\n\n"
            "내부 오류:\n" + "\n".join(errors[-3:])
        )

    security_ok, security_module_name, security_error = try_register_file_path_security_module(hwp)

    try:
        hwp.XHwpWindows.Item(0).Visible = bool(visible)
    except Exception:
        pass

    return hwp, security_ok, security_module_name, security_error


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
) -> HwpToHwpxBatchResult:
    def emit(message: str = "") -> None:
        if log is not None:
            log(message)

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

    emit("===== HWP → HWPX 변환 시작 =====")
    emit(f"처리 대상 파일: {len(ordered)}개")
    emit("저장 방식: 원본과 같은 폴더에 같은 이름의 HWPX 생성")
    emit("원본 처리: 변환 성공 시 HWP 삭제")
    emit("기존 HWPX 처리: 같은 이름이 있으면 덮어쓰기")
    emit(f"한글 창 보이기: {'예' if visible else '아니오'}")

    try:
        hwp, security_ok, security_module_name, security_error = create_hwp_object(visible=visible)
        if security_ok:
            emit(f"보안모듈 등록: 성공({security_module_name})")
        else:
            emit("보안모듈 등록: 실패 또는 미등록")
            if security_error:
                emit(f"  - 사유: {security_error}")
            emit("  - 한글 파일 접근 허용 창이 뜨면 허용을 선택해 주세요.")
        emit()

        for index, src_path in enumerate(ordered, start=1):
            dst_path = output_hwpx_path(src_path)
            overwritten = dst_path.exists()

            set_status(src_path, "변환 중")
            emit(f"[{index}/{len(ordered)}] {src_path.name}")
            emit(f"  - 원본 HWP: {src_path}")
            emit(f"  - 변환 HWPX: {dst_path}")
            if overwritten:
                emit("  - 안내: 같은 이름의 HWPX가 있어 덮어씁니다.")

            try:
                convert_hwp_to_hwpx_via_temp(hwp, src_path, dst_path)
                if not dst_path.exists() or dst_path.stat().st_size == 0:
                    raise RuntimeError("변환된 HWPX 파일을 확인할 수 없습니다.")

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
        if hwp is not None:
            try:
                hwp.Quit()
            except Exception:
                pass
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass

    emit("===== 완료 =====")
    emit(f"성공: {batch.success_count}개")
    emit(f"원본 삭제 실패: {batch.delete_fail_count}개")
    emit(f"변환 실패: {batch.fail_count}개")
    emit(f"기존 HWPX 덮어쓰기: {batch.overwrite_count}개")
    return batch
