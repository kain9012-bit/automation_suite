from __future__ import annotations

import ctypes
import os
import shutil
import uuid
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


LogCallback = Callable[[str], None]


@dataclass
class FolderSummary:
    path: Path
    file_count: int
    subfolder_count: int


@dataclass
class UnpackResult:
    moved_count: int = 0
    removed_folder_count: int = 0
    error_count: int = 0
    skipped_count: int = 0
    redundant_folders: list[Path] = field(default_factory=list)
    first_parent: Path | None = None


def _signed_hresult(value) -> int:
    value = int(value) & 0xFFFFFFFF
    if value & 0x80000000:
        value -= 0x100000000
    return value


def _hresult_failed(value) -> bool:
    return _signed_hresult(value) < 0


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", wintypes.BYTE * 8),
    ]

    def __init__(self, guid_string: str):
        super().__init__()
        value = uuid.UUID(guid_string)
        self.Data1 = value.time_low
        self.Data2 = value.time_mid
        self.Data3 = value.time_hi_version
        self.Data4[0] = value.clock_seq_hi_variant
        self.Data4[1] = value.clock_seq_low
        node_bytes = value.node.to_bytes(6, "big")
        for index, byte in enumerate(node_bytes):
            self.Data4[2 + index] = byte


def _com_method(ptr, index: int, restype, *argtypes):
    vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    prototype_factory = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
    prototype = prototype_factory(restype, ctypes.c_void_p, *argtypes)
    return prototype(vtbl[index])


def _com_release(ptr) -> None:
    if not ptr:
        return
    try:
        release = _com_method(ptr, 2, ctypes.c_ulong)
        release(ptr)
    except Exception:
        pass


def select_folders_multi_windows(title: str = "폴더를 선택하세요") -> list[str] | None:
    """Return selected folder paths, [] on cancel, or None when native multi-select is unavailable."""
    if os.name != "nt":
        return None

    try:
        ole32 = ctypes.OleDLL("ole32")
    except Exception:
        return None

    clsid_file_open_dialog = GUID("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7")
    iid_file_open_dialog = GUID("D57C7288-D4AD-4768-BE02-9D969532D960")

    clsctx_inproc_server = 0x1
    fos_pickfolders = 0x00000020
    fos_forcefilesystem = 0x00000040
    fos_allowmultiselect = 0x00000200
    fos_pathmustexist = 0x00000800
    sigdn_filesyspath = 0x80058000

    ole32.CoInitialize.argtypes = [ctypes.c_void_p]
    ole32.CoInitialize.restype = ctypes.c_long
    ole32.CoUninitialize.argtypes = []
    ole32.CoUninitialize.restype = None
    ole32.CoCreateInstance.argtypes = [
        ctypes.POINTER(GUID),
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    ole32.CoCreateInstance.restype = ctypes.c_long
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole32.CoTaskMemFree.restype = None

    coinit_hr = ole32.CoInitialize(None)
    coinit_ok = _signed_hresult(coinit_hr) in (0, 1)
    dialog = ctypes.c_void_p()

    try:
        hr = ole32.CoCreateInstance(
            ctypes.byref(clsid_file_open_dialog),
            None,
            clsctx_inproc_server,
            ctypes.byref(iid_file_open_dialog),
            ctypes.byref(dialog),
        )
        if _hresult_failed(hr) or not dialog:
            return None

        try:
            options = wintypes.DWORD(0)
            get_options = _com_method(dialog, 10, ctypes.c_long, ctypes.POINTER(wintypes.DWORD))
            set_options = _com_method(dialog, 9, ctypes.c_long, wintypes.DWORD)
            set_title = _com_method(dialog, 17, ctypes.c_long, wintypes.LPCWSTR)
            show = _com_method(dialog, 3, ctypes.c_long, wintypes.HWND)
            get_results = _com_method(dialog, 27, ctypes.c_long, ctypes.POINTER(ctypes.c_void_p))

            get_options(dialog, ctypes.byref(options))
            new_options = (
                options.value
                | fos_pickfolders
                | fos_forcefilesystem
                | fos_allowmultiselect
                | fos_pathmustexist
            )
            set_options(dialog, new_options)
            set_title(dialog, title)

            hr = show(dialog, wintypes.HWND(0))
            if _hresult_failed(hr):
                return []

            item_array = ctypes.c_void_p()
            hr = get_results(dialog, ctypes.byref(item_array))
            if _hresult_failed(hr) or not item_array:
                return []

            paths: list[str] = []
            try:
                get_count = _com_method(item_array, 7, ctypes.c_long, ctypes.POINTER(wintypes.DWORD))
                get_item_at = _com_method(
                    item_array,
                    8,
                    ctypes.c_long,
                    wintypes.DWORD,
                    ctypes.POINTER(ctypes.c_void_p),
                )
                count = wintypes.DWORD(0)
                hr = get_count(item_array, ctypes.byref(count))
                if _hresult_failed(hr):
                    return []

                for index in range(count.value):
                    shell_item = ctypes.c_void_p()
                    hr = get_item_at(item_array, index, ctypes.byref(shell_item))
                    if _hresult_failed(hr) or not shell_item:
                        continue

                    try:
                        get_display_name = _com_method(
                            shell_item,
                            5,
                            ctypes.c_long,
                            wintypes.DWORD,
                            ctypes.POINTER(ctypes.c_void_p),
                        )
                        path_ptr = ctypes.c_void_p()
                        hr = get_display_name(shell_item, sigdn_filesyspath, ctypes.byref(path_ptr))
                        if not _hresult_failed(hr) and path_ptr:
                            folder_path = ctypes.cast(path_ptr, ctypes.c_wchar_p).value
                            ole32.CoTaskMemFree(path_ptr)
                            if folder_path and os.path.isdir(folder_path):
                                paths.append(folder_path)
                    finally:
                        _com_release(shell_item)
            finally:
                _com_release(item_array)

            return paths
        finally:
            _com_release(dialog)
    except Exception:
        return None
    finally:
        if coinit_ok:
            try:
                ole32.CoUninitialize()
            except Exception:
                pass


def safe_filename(name: str) -> str:
    invalid = '\\/:*?"<>|'
    result = name or ""
    for char in invalid:
        result = result.replace(char, "_")
    result = result.strip(" .")
    return result or "이름없음"


def make_unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    index = 1
    while True:
        candidate = path.with_name(f"{path.stem}({index}){path.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def normalize_folder_path(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def is_drive_root(path: str | Path) -> bool:
    abs_path = os.path.abspath(os.fspath(path))
    parent = os.path.dirname(abs_path)
    return parent == abs_path


def is_child_path(child: str | Path, parent: str | Path) -> bool:
    try:
        child_abs = normalize_folder_path(child)
        parent_abs = normalize_folder_path(parent)
        common = os.path.commonpath([child_abs, parent_abs])
        return common == parent_abs and child_abs != parent_abs
    except Exception:
        return False


def count_files(folder_path: str | Path, recursive: bool = True) -> int:
    total = 0
    try:
        if recursive:
            for _, _, files in os.walk(folder_path):
                total += len(files)
        else:
            for name in os.listdir(folder_path):
                path = Path(folder_path) / name
                if path.is_file():
                    total += 1
    except Exception:
        pass
    return total


def count_subfolders(folder_path: str | Path) -> int:
    total = 0
    try:
        for _, dirs, _ in os.walk(folder_path):
            total += len(dirs)
    except Exception:
        pass
    return total


def summarize_folder(folder_path: str | Path, recursive: bool = True) -> FolderSummary:
    path = Path(folder_path).resolve()
    return FolderSummary(
        path=path,
        file_count=count_files(path, recursive=recursive),
        subfolder_count=count_subfolders(path),
    )


def collect_files(folder_path: str | Path, recursive: bool = True) -> list[Path]:
    result: list[Path] = []
    folder = Path(folder_path)

    try:
        if recursive:
            for current, _, files in os.walk(folder):
                current_path = Path(current)
                for filename in files:
                    result.append(current_path / filename)
        else:
            for path in folder.iterdir():
                if path.is_file():
                    result.append(path)
    except Exception:
        pass

    return result


def remove_empty_dirs(folder_path: str | Path) -> list[Path]:
    removed: list[Path] = []
    folder = Path(folder_path)
    if not folder.is_dir():
        return removed

    for current, _, _ in os.walk(folder, topdown=False):
        current_path = Path(current)
        try:
            current_path.rmdir()
            removed.append(current_path)
        except OSError:
            pass
    return removed


def filter_redundant_folders(folders: list[Path], recursive: bool) -> tuple[list[Path], list[Path]]:
    if not recursive:
        return folders, []

    result: list[Path] = []
    removed: list[Path] = []

    normalized = [Path(folder).resolve() for folder in folders]
    for folder in normalized:
        redundant = any(folder != other and is_child_path(folder, other) for other in normalized)
        if redundant:
            removed.append(folder)
        else:
            result.append(folder)

    return result, removed


def unpack_folders(
    folders: list[Path],
    recursive: bool = True,
    prefix_folder: bool = False,
    log: LogCallback | None = None,
) -> UnpackResult:
    def emit(message: str = "") -> None:
        if log is not None:
            log(message)

    target_folders, redundant_folders = filter_redundant_folders(folders, recursive=recursive)
    result = UnpackResult(redundant_folders=redundant_folders)

    emit("===== 파일 꺼내기 시작 =====")
    emit(f"처리 대상 폴더: {len(target_folders)}개")
    emit(f"하위 폴더 파일 포함: {'예' if recursive else '아니오'}")
    emit(f"파일명 앞에 폴더명 붙이기: {'예' if prefix_folder else '아니오'}")
    if redundant_folders:
        emit(f"상위 폴더와 중복되어 제외된 하위 폴더: {len(redundant_folders)}개")
    emit()

    for folder_path in target_folders:
        folder = Path(folder_path).resolve()
        if not folder.is_dir():
            result.skipped_count += 1
            emit(f"[건너뜀] 폴더 없음: {folder}")
            continue

        folder_name = folder.name
        parent_folder = folder.parent
        if result.first_parent is None:
            result.first_parent = parent_folder

        files = collect_files(folder, recursive=recursive)
        emit(f"[{folder_name}]")
        emit(f"  - 파일 이동 위치: {parent_folder}")
        emit(f"  - 이동 대상 파일: {len(files)}개")

        for src_path in files:
            try:
                if not src_path.is_file():
                    continue

                original_name = src_path.name
                target_name = f"{safe_filename(folder_name)}_{original_name}" if prefix_folder else original_name
                target_name = safe_filename(target_name)
                dst_path = make_unique_path(parent_folder / target_name)

                shutil.move(str(src_path), str(dst_path))
                result.moved_count += 1
                emit(f"    - 이동: {original_name} -> {dst_path.name}")
            except Exception as exc:
                result.error_count += 1
                emit(f"    ! 파일 이동 실패: {src_path} / {exc}")

        removed_dirs = remove_empty_dirs(folder)
        if removed_dirs:
            result.removed_folder_count += len(removed_dirs)
            emit(f"  - 삭제된 빈 폴더: {len(removed_dirs)}개")
        else:
            emit("  - 삭제할 빈 폴더 없음")
        emit()

    emit("===== 완료 =====")
    emit(f"이동한 파일: {result.moved_count}개")
    emit(f"삭제한 빈 폴더: {result.removed_folder_count}개")
    emit(f"건너뜀: {result.skipped_count}개")
    emit(f"오류: {result.error_count}개")
    return result
