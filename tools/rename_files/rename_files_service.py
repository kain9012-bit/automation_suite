from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

MODE_REPLACE = "replace"
MODE_PREFIX = "prefix"
MODE_SUFFIX = "suffix"


@dataclass
class RenameResult:
    success_count: int
    conflict_count: int
    conflict_list: list[str]
    # 바꾸지 못한 파일: [{"name": 원래 이름, "error": 이유}]
    failed: list[dict] = field(default_factory=list)


# 윈도에서 파일 이름으로 쓸 수 없는 이름(확장자가 붙어도 안 된다).
_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
_BAD_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')


def invalid_name_reason(name: str) -> str | None:
    """새 파일 이름을 윈도에서 쓸 수 없으면 그 이유(한국어), 쓸 수 있으면 None."""
    if not name or not name.strip(" ."):
        return "새 이름이 비어 있습니다"
    if "/" in name or "\\" in name:
        return "이름에 / 나 \\ 는 쓸 수 없습니다"
    if _BAD_CHARS.search(name):
        return '이름에 쓸 수 없는 문자(< > : " | ? *)가 들어 있습니다'
    if name[-1] in " .":
        return "이름 끝에 점(.)이나 공백은 쓸 수 없습니다"
    if name.split(".", 1)[0].strip().upper() in _RESERVED_NAMES:
        return "윈도에서 쓸 수 없는 이름(CON·PRN·AUX·NUL·COM1·LPT1 등)입니다"
    if len(name) > 255:
        return "이름이 너무 깁니다(255자 이하)"
    return None


def list_files_in_folder(folder: Path) -> list[Path]:
    return sorted([path for path in folder.iterdir() if path.is_file()], key=lambda item: item.name.lower())


def build_changes(
    selected_files: list[Path],
    before: str,
    after: str,
    mode: str = MODE_REPLACE,
    failed: list[dict] | None = None,
) -> list[tuple[Path, Path]]:
    """바꿀 (원래 경로, 새 경로) 목록.

    새 이름을 쓸 수 없는 파일은 failed 에 {"name", "error"} 로 담고 건너뛴다.
    failed 를 주지 않으면 그런 파일에서 ValueError(한국어 이유)를 낸다.
    """
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
            new_name = new_stem + suffix
            reason = "새 이름이 비어 있습니다" if not new_stem.strip(" .") else invalid_name_reason(new_name)
            if reason:
                if failed is None:
                    raise ValueError(f"{path.name} → {new_name}: {reason}")
                failed.append({"name": path.name, "error": f"{reason} ({new_name})"})
                continue
            changes.append((path, path.with_name(new_name)))

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
    failed: list[dict] = []

    for old_path, new_path in changes:
        try:
            if new_path.exists() and new_path.resolve() != old_path.resolve():
                conflict_count += 1
                conflict_list.append(f"{old_path.name} -> {new_path.name} (이미 있음)")
                failed.append({"name": old_path.name, "error": f"같은 이름의 파일이 이미 있습니다 ({new_path.name})"})
                continue

            old_path.rename(new_path)
            success_count += 1
        except Exception as exc:
            conflict_count += 1
            conflict_list.append(f"{old_path.name} -> {new_path.name} ({exc})")
            failed.append({"name": old_path.name, "error": f"이름을 바꾸지 못했습니다 ({exc})"})

    return RenameResult(
        success_count=success_count,
        conflict_count=conflict_count,
        conflict_list=conflict_list,
        failed=failed,
    )


def update_selected_paths_after_rename(
    selected_files: list[Path],
    changes: list[tuple[Path, Path]],
) -> list[Path]:
    mapping = {old: new for old, new in changes}
    return [mapping.get(path, path) for path in selected_files]
