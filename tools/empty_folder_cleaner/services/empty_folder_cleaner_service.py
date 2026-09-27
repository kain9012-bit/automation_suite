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


def is_drive_root(path: str | Path, pathmod=os.path) -> bool:
    """드라이브 맨 위(D:\\)나 네트워크 공유의 맨 위(\\\\서버\\공유)인지.

    pathmod 는 시험용이다(리눅스에서 윈도 경로 규칙을 확인할 때 ntpath 를 넘긴다).
    """
    abs_path = pathmod.abspath(os.fspath(path))
    _drive, rest = pathmod.splitdrive(abs_path)
    if not rest.strip("\\/"):
        return True
    return pathmod.dirname(abs_path) == abs_path


def is_link_or_junction(path: str | Path) -> bool:
    """바로가기 폴더(심볼릭 링크·윈도 정션)인지. 이런 폴더는 따라 들어가지도, 지우지도 않는다."""
    target = os.fspath(path)
    try:
        if os.path.islink(target):
            return True
        isjunction = getattr(os.path, "isjunction", None)
        if isjunction is not None:
            return bool(isjunction(target))
        if os.name == "nt":  # 파이썬 3.12 이전: 정션(마운트 지점) 표식을 직접 본다.
            return getattr(os.lstat(target), "st_reparse_tag", 0) == 0xA0000003
    except OSError:
        return False
    return False


def is_inside(child: str | Path, root: str | Path) -> bool:
    """child 가 root 와 같거나 그 안쪽인지(링크를 풀지 않고 글자 그대로 비교)."""
    try:
        child_abs = normalize_folder_path(child)
        root_abs = normalize_folder_path(root)
        return os.path.commonpath([child_abs, root_abs]) == root_abs
    except ValueError:
        return False


def _passes_through_link(folder: Path, root: Path) -> bool:
    """root 아래에서 folder 까지 가는 길에 링크·정션 폴더가 끼어 있는지(folder 자신 포함)."""
    current = folder
    root_norm = normalize_folder_path(root)
    while True:
        if is_link_or_junction(current):
            return True
        if normalize_folder_path(current) == root_norm:
            return False
        parent = current.parent
        if parent == current:
            return False
        current = parent


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

    # resolve() 는 정션·링크를 풀어 고른 폴더 밖을 가리킬 수 있으므로 글자 그대로의 절대 경로를 쓴다.
    root = Path(os.path.abspath(os.fspath(root_folder)))
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
    if is_link_or_junction(root):
        raise RuntimeError("바로가기(정션·링크) 폴더는 기준 폴더로 선택할 수 없습니다. 실제 폴더를 골라 주세요.")

    def on_error(exc: OSError) -> None:
        result.errors.append(f"{getattr(exc, 'filename', '') or root}: {exc}")

    # 위에서부터 훑되 링크·정션 폴더 안으로는 들어가지 않는다. 링크·정션은 '내용물'로 본다
    # (그 폴더를 지우려면 링크를 지워야 하므로 비어 있지 않은 것으로 친다).
    visited: list[tuple[str, bool, list[str]]] = []
    for current, dirs, files in os.walk(root, onerror=on_error):
        links = [name for name in dirs if is_link_or_junction(os.path.join(current, name))]
        dirs[:] = [name for name in dirs if name not in links]
        visited.append((current, bool(files) or bool(links), [os.path.join(current, name) for name in dirs]))

    root_norm = normalize_folder_path(root)
    # 뒤집으면 안쪽 폴더가 먼저 나온다.
    for current, has_content, children in reversed(visited):
        current_path = Path(current)
        try:
            child_empty = all(normalize_folder_path(child) in empty_set for child in children)
            if has_content or not child_empty:
                continue
            empty_set.add(normalize_folder_path(current_path))
            if normalize_folder_path(current_path) == root_norm and not include_root:
                continue
            result.folders.append(current_path)
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
    root: str | Path | None = None,
) -> EmptyFolderDeleteResult:
    """빈 폴더를 지운다. root 를 주면 그 안쪽 폴더만 지운다.

    링크·정션 폴더, 그리고 링크·정션을 거쳐야 닿는 폴더(실제로는 다른 곳에 있는 폴더)는 지우지 않는다.
    """
    def emit(message: str = "") -> None:
        if log is not None:
            log(message)

    result = EmptyFolderDeleteResult()
    root_path = Path(os.path.abspath(os.fspath(root))) if root is not None else None
    unique: dict[str, Path] = {}
    for folder in folders:
        path = Path(os.path.abspath(os.fspath(folder)))
        unique[normalize_folder_path(path)] = path

    targets = sorted(unique.values(), key=lambda path: (len(path.parts), str(path).lower()), reverse=True)

    emit("===== 빈 폴더 삭제 시작 =====")
    emit(f"삭제 대상 후보: {len(targets)}개")
    emit()

    for folder in targets:
        try:
            if root_path is not None and not is_inside(folder, root_path):
                result.skipped_count += 1
                emit(f"[건너뜀] 기준 폴더 밖: {folder}")
                continue
            if is_drive_root(folder):
                result.skipped_count += 1
                emit(f"[건너뜀] 드라이브 루트: {folder}")
                continue
            if (
                _passes_through_link(folder, root_path)
                if root_path is not None
                else is_link_or_junction(folder)
            ):
                result.skipped_count += 1
                emit(f"[건너뜀] 바로가기(정션·링크): {folder}")
                continue
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
