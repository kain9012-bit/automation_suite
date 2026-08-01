from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

LogCallback = Callable[[str], None]


@dataclass
class EmptyFolderScanResult:
    root_folder: Path
    folders: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class EmptyFolderDeleteResult:
    deleted_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    deleted_folders: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def normalize_folder_path(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def is_drive_root(path: str | Path) -> bool:
    abs_path = os.path.abspath(os.fspath(path))
    parent = os.path.dirname(abs_path)
    return parent == abs_path


def folder_is_empty(path: Path) -> bool:
    try:
        return path.is_dir() and not any(path.iterdir())
    except Exception:
        return False


def scan_empty_folders(
    root_folder: str | Path,
    include_root: bool = False,
    log: LogCallback | None = None,
) -> EmptyFolderScanResult:
    def emit(message: str = "") -> None:
        if log is not None:
            log(message)

    root = Path(root_folder).resolve()
    result = EmptyFolderScanResult(root_folder=root)
    empty_set: set[str] = set()

    emit("===== 빈 폴더 스캔 시작 =====")
    emit(f"기준 폴더: {root}")
    emit(f"기준 폴더 자체 포함: {'예' if include_root else '아니오'}")
    emit()

    if not root.is_dir():
        raise RuntimeError("기준 폴더가 존재하지 않습니다.")
    if is_drive_root(root):
        raise RuntimeError("드라이브 루트 폴더는 기준 폴더로 선택할 수 없습니다.")

    for current, dirs, files in os.walk(root, topdown=False):
        current_path = Path(current).resolve()
        if current_path == root and not include_root:
            continue

        try:
            child_empty = True
            for dirname in dirs:
                child_path = (current_path / dirname).resolve()
                if normalize_folder_path(child_path) not in empty_set:
                    child_empty = False
                    break

            if not files and child_empty:
                result.folders.append(current_path)
                empty_set.add(normalize_folder_path(current_path))
        except Exception as exc:
            result.errors.append(f"{current_path}: {exc}")

    result.folders.sort(key=lambda path: (len(path.parts), str(path).lower()), reverse=True)
    emit(f"찾은 빈 폴더: {len(result.folders)}개")
    if result.errors:
        emit(f"스캔 오류: {len(result.errors)}건")
    emit("===== 스캔 완료 =====")
    return result


def delete_empty_folders(
    folders: list[Path],
    log: LogCallback | None = None,
) -> EmptyFolderDeleteResult:
    def emit(message: str = "") -> None:
        if log is not None:
            log(message)

    result = EmptyFolderDeleteResult()
    unique: dict[str, Path] = {}
    for folder in folders:
        path = Path(folder).resolve()
        unique[normalize_folder_path(path)] = path

    targets = sorted(unique.values(), key=lambda path: (len(path.parts), str(path).lower()), reverse=True)

    emit("===== 빈 폴더 삭제 시작 =====")
    emit(f"삭제 대상 후보: {len(targets)}개")
    emit()

    for folder in targets:
        try:
            if not folder.is_dir():
                result.skipped_count += 1
                emit(f"[건너뜀] 폴더 없음: {folder}")
                continue
            if not folder_is_empty(folder):
                result.skipped_count += 1
                emit(f"[건너뜀] 비어 있지 않음: {folder}")
                continue

            folder.rmdir()
            result.deleted_count += 1
            result.deleted_folders.append(folder)
            emit(f"[삭제] {folder}")
        except Exception as exc:
            result.error_count += 1
            message = f"{folder}: {exc}"
            result.errors.append(message)
            emit(f"[오류] {message}")

    emit()
    emit("===== 완료 =====")
    emit(f"삭제: {result.deleted_count}개")
    emit(f"건너뜀: {result.skipped_count}개")
    emit(f"오류: {result.error_count}개")
    return result
