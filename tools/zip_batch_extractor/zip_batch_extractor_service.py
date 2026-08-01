from __future__ import annotations

import os
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable


OUTPUT_ORIGINAL = "압축파일 원본 위치"
OUTPUT_CUSTOM = "지정 위치"
EXTRACT_TO_NAMED_FOLDER = "압축파일명 폴더 안에 풀기"
EXTRACT_DIRECT = "폴더 만들지 않고 바로 풀기"

LogCallback = Callable[[str], None]


@dataclass
class ZipExtractResult:
    zip_path: Path
    target_folder: Path | None = None
    file_count: int = 0
    folder_count: int = 0
    skip_count: int = 0
    error_count: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class BatchExtractResult:
    success_count: int = 0
    fail_count: int = 0
    total_files: int = 0
    total_errors: int = 0
    opened_folder: Path | None = None
    results: list[ZipExtractResult] = field(default_factory=list)


def format_size(num_bytes) -> str:
    try:
        value = int(num_bytes)
    except Exception:
        return ""

    if value >= 1024 * 1024 * 1024:
        return f"{value / (1024 * 1024 * 1024):,.2f} GB"
    if value >= 1024 * 1024:
        return f"{value / (1024 * 1024):,.2f} MB"
    if value >= 1024:
        return f"{value / 1024:,.2f} KB"
    return f"{value:,} B"


def safe_name(name: str) -> str:
    name = name or ""
    name = name.replace("\x00", "")
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = name.strip(" .")
    return name or "이름없음"


def safe_relative_path(path: str) -> Path | None:
    path = (path or "").replace("\\", "/")
    path = path.lstrip("/")
    parts: list[str] = []

    for part in path.split("/"):
        part = part.strip()
        if not part or part in (".", ".."):
            continue

        part = re.sub(r"^[a-zA-Z]:", "", part)
        part = safe_name(part)
        if part:
            parts.append(part)

    if not parts:
        return None
    return Path(*parts)


def make_unique_file_path(path: Path) -> Path:
    if not path.exists():
        return path

    index = 1
    while True:
        candidate = path.with_name(f"{path.stem}({index}){path.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def make_unique_folder_path(path: Path) -> Path:
    if not path.exists():
        return path

    index = 1
    while True:
        candidate = path.with_name(f"{path.name}({index})")
        if not candidate.exists():
            return candidate
        index += 1


def get_downloads_folder() -> Path:
    downloads = Path.home() / "Downloads"
    if downloads.is_dir():
        return downloads
    return Path.home()


def decode_zip_member_name(info: zipfile.ZipInfo) -> str:
    name = info.filename
    if info.flag_bits & 0x800:
        return name

    try:
        return name.encode("cp437").decode("cp949")
    except Exception:
        return name


def should_skip_junk_file(relative_path: str) -> bool:
    normalized = relative_path.replace("\\", "/")
    parts = normalized.split("/")
    if "__MACOSX" in parts:
        return True

    filename = os.path.basename(normalized)
    return filename in (".DS_Store", "Thumbs.db", "desktop.ini")


def is_zip_file(path: str | Path) -> bool:
    file_path = Path(path)
    return file_path.is_file() and file_path.suffix.lower() == ".zip"


def zip_file_display_name(path: str | Path) -> str:
    return Path(path).name


def zip_stem_name(path: str | Path) -> str:
    return Path(path).stem


def scan_zip_files(folder: str | Path, include_subfolders: bool = True) -> list[Path]:
    root = Path(folder)
    result: list[Path] = []

    if include_subfolders:
        for current, _, files in os.walk(root):
            current_path = Path(current)
            for filename in files:
                path = current_path / filename
                if is_zip_file(path):
                    result.append(path.resolve())
    else:
        for path in root.iterdir():
            if is_zip_file(path):
                result.append(path.resolve())

    return sorted(result, key=lambda item: str(item).lower())


def extract_one_zip(
    zip_path: str | Path,
    output_location_mode: str,
    extract_mode: str,
    custom_output_folder: str | Path,
    exclude_junk: bool,
    password_text: str,
    log_func: LogCallback | None = None,
) -> ZipExtractResult:
    def log(message: str) -> None:
        if log_func is not None:
            log_func(message)

    zip_file = Path(zip_path).resolve()
    result = ZipExtractResult(zip_path=zip_file)

    if output_location_mode == OUTPUT_CUSTOM:
        base_output = Path(custom_output_folder).resolve()
    else:
        base_output = zip_file.parent

    if not base_output.is_dir():
        raise RuntimeError("압축 해제 저장 위치가 존재하지 않습니다.")

    if extract_mode == EXTRACT_TO_NAMED_FOLDER:
        target_folder = make_unique_folder_path(base_output / safe_name(zip_stem_name(zip_file)))
        target_folder.mkdir(parents=True, exist_ok=True)
    else:
        target_folder = base_output

    result.target_folder = target_folder
    target_abs = target_folder.resolve()
    pwd = password_text.encode("utf-8") if password_text else None

    try:
        with zipfile.ZipFile(zip_file, "r") as archive:
            for info in archive.infolist():
                try:
                    raw_name = decode_zip_member_name(info)
                    relative_path = safe_relative_path(raw_name)
                    if relative_path is None:
                        result.skip_count += 1
                        continue

                    if exclude_junk and should_skip_junk_file(raw_name):
                        result.skip_count += 1
                        continue

                    dest_path = (target_folder / relative_path).resolve()
                    if not (dest_path == target_abs or target_abs in dest_path.parents):
                        result.skip_count += 1
                        continue

                    if info.is_dir() or raw_name.endswith(("/", "\\")):
                        dest_path.mkdir(parents=True, exist_ok=True)
                        result.folder_count += 1
                        continue

                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    dest_path = make_unique_file_path(dest_path)

                    with archive.open(info, "r", pwd=pwd) as src, open(dest_path, "wb") as dst:
                        shutil.copyfileobj(src, dst, length=1024 * 128)

                    try:
                        modified = datetime(*info.date_time)
                        timestamp = modified.timestamp()
                        os.utime(dest_path, (timestamp, timestamp))
                    except Exception:
                        pass

                    result.file_count += 1
                except RuntimeError as exc:
                    result.error_count += 1
                    result.errors.append(f"{info.filename}: {exc}")
                except Exception as exc:
                    result.error_count += 1
                    result.errors.append(f"{info.filename}: {exc}")
    except zipfile.BadZipFile:
        raise RuntimeError("정상적인 ZIP 파일이 아닙니다.")

    log(f"  - 저장 위치: {target_folder}")
    log(
        "  - "
        f"파일 {result.file_count}개, "
        f"폴더 {result.folder_count}개, "
        f"건너뜀 {result.skip_count}개, "
        f"오류 {result.error_count}개"
    )
    return result


def extract_zip_batch(
    zip_files: list[Path],
    output_location_mode: str,
    extract_mode: str,
    custom_output_folder: str | Path,
    exclude_junk: bool,
    password_text: str,
    log_func: LogCallback | None = None,
) -> BatchExtractResult:
    def log(message: str = "") -> None:
        if log_func is not None:
            log_func(message)

    batch = BatchExtractResult()
    log("===== ZIP 일괄 풀기 시작 =====")
    log(f"대상 ZIP 파일: {len(zip_files)}개")
    log(f"저장 위치: {output_location_mode}")
    log(f"풀기 방식: {extract_mode}")
    if output_location_mode == OUTPUT_CUSTOM:
        log(f"지정 위치: {custom_output_folder}")
    log(f"불필요 파일 제외: {'예' if exclude_junk else '아니오'}")
    log(f"공통 비밀번호 사용: {'예' if password_text else '아니오'}")
    log()

    for index, zip_file in enumerate(zip_files, start=1):
        log(f"[{index}/{len(zip_files)}] {Path(zip_file).name}")
        try:
            result = extract_one_zip(
                zip_path=zip_file,
                output_location_mode=output_location_mode,
                extract_mode=extract_mode,
                custom_output_folder=custom_output_folder,
                exclude_junk=exclude_junk,
                password_text=password_text,
                log_func=log,
            )
            batch.success_count += 1
            batch.total_files += result.file_count
            batch.total_errors += result.error_count
            batch.results.append(result)

            if batch.opened_folder is None:
                batch.opened_folder = result.target_folder

            if result.errors:
                for error in result.errors[:5]:
                    log(f"    ! {error}")
                if len(result.errors) > 5:
                    log(f"    ! 추가 오류 {len(result.errors) - 5}건 생략")
        except Exception as exc:
            batch.fail_count += 1
            batch.total_errors += 1
            log(f"  ! 실패: {exc}")
        log()

    log("===== 완료 =====")
    log(f"성공 ZIP: {batch.success_count}개")
    log(f"실패 ZIP: {batch.fail_count}개")
    log(f"압축 해제 파일: {batch.total_files}개")
    log(f"오류: {batch.total_errors}개")
    return batch
