from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

MODE_REPLACE = "replace"
MODE_PREFIX = "prefix"
MODE_SUFFIX = "suffix"


@dataclass
class RenameResult:
    success_count: int
    conflict_count: int
    conflict_list: list[str]


def list_files_in_folder(folder: Path) -> list[Path]:
    return sorted([path for path in folder.iterdir() if path.is_file()], key=lambda item: item.name.lower())


def build_changes(
    selected_files: list[Path],
    before: str,
    after: str,
    mode: str = MODE_REPLACE,
) -> list[tuple[Path, Path]]:
    changes: list[tuple[Path, Path]] = []

    for path in selected_files:
        stem = path.stem
        suffix = path.suffix

        if mode == MODE_PREFIX:
            new_stem = f"{after}{stem}"
        elif mode == MODE_SUFFIX:
            new_stem = f"{stem}{after}"
        else:
            new_stem = stem.replace(before, after)

        if new_stem != stem:
            changes.append((path, path.with_name(new_stem + suffix)))

    return changes


def build_preview_lines(changes: list[tuple[Path, Path]], max_preview: int = 8) -> list[str]:
    preview_lines: list[str] = []

    for index, (old, new) in enumerate(changes[:max_preview], start=1):
        preview_lines.append(f"{index}. {old.name} -> {new.name}")

    if len(changes) > max_preview:
        preview_lines.append(f"... 그 외 {len(changes) - max_preview}개 파일")

    return preview_lines


def apply_changes(changes: list[tuple[Path, Path]]) -> RenameResult:
    success_count = 0
    conflict_count = 0
    conflict_list: list[str] = []

    for old_path, new_path in changes:
        try:
            if new_path.exists() and new_path.resolve() != old_path.resolve():
                conflict_count += 1
                conflict_list.append(f"{old_path.name} -> {new_path.name} (이미 있음)")
                continue

            old_path.rename(new_path)
            success_count += 1
        except Exception as exc:
            conflict_count += 1
            conflict_list.append(f"{old_path.name} -> {new_path.name} ({exc})")

    return RenameResult(
        success_count=success_count,
        conflict_count=conflict_count,
        conflict_list=conflict_list,
    )


def update_selected_paths_after_rename(
    selected_files: list[Path],
    changes: list[tuple[Path, Path]],
) -> list[Path]:
    mapping = {old: new for old, new in changes}
    return [mapping.get(path, path) for path in selected_files]
