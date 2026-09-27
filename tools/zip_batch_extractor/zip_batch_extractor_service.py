from __future__ import annotations

import os
import re
import shutil
import zipfile
import zlib
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
    # errors 와 같은 순서로, 파일마다 풀지 못한 이유(한국어)
    reasons: list[str] = field(default_factory=list)


@dataclass
class BatchExtractResult:
    success_count: int = 0
    fail_count: int = 0
    total_files: int = 0
    total_errors: int = 0
    opened_folder: Path | None = None
    results: list[ZipExtractResult] = field(default_factory=list)
    # 풀지 못했거나 일부만 푼 ZIP: [{"name": ZIP 이름, "error": 이유}]
    failed: list[dict] = field(default_factory=list)


REASON_NEED_PASSWORD = "암호가 걸린 ZIP입니다 — 압축 비밀번호를 입력해 주세요"
REASON_BAD_PASSWORD = "암호가 맞지 않습니다"
REASON_CORRUPT = "손상된 ZIP 파일입니다"
REASON_BAD_PASSWORD_OR_CORRUPT = "암호가 맞지 않거나 손상된 ZIP 파일입니다"
REASON_UNSUPPORTED = "지원하지 않는 압축 방식(AES 암호 등)입니다 — 반디집 등으로 풀어 주세요"

# 파이썬 zipfile 이 풀 수 있는 압축 방식. 7-Zip·반디집의 AES 암호(99)·Deflate64(9) 등은 못 푼다.
SUPPORTED_COMPRESSION = {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED, zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA}


try:
    import lzma
    _LZMA_ERRORS: tuple = (lzma.LZMAError,)
except ImportError:  # pragma: no cover
    _LZMA_ERRORS = ()


class ZipExtractError(RuntimeError):
    """ZIP 하나(또는 그 안 파일 하나)를 풀지 못한 이유. 문구는 사용자에게 그대로 보인다."""


def password_candidates(password_text: str) -> list[bytes]:
    """입력한 비밀번호를 바이트로. 한글 비밀번호는 윈도 압축 프로그램이 cp949 로 걸기도 해서 둘 다 해 본다."""
    if not password_text:
        return []
    candidates = [password_text.encode("utf-8")]
    try:
        legacy = password_text.encode("cp949")
    except UnicodeEncodeError:
        legacy = None
    if legacy is not None and legacy not in candidates:
        candidates.append(legacy)
    return candidates


def _copy_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo, dest_path: Path, pwd: bytes | None) -> None:
    """ZIP 안 파일 하나를 dest_path 로 푼다. 도중에 실패하면 쓰다 만 파일을 지운다."""
    try:
        with archive.open(info, "r", pwd=pwd) as src, open(dest_path, "wb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 128)
    except BaseException:
        # dest_path 는 make_unique_file_path 로 고른, 원래 없던 이름이라 지워도 된다.
        try:
            if dest_path.exists():
                dest_path.unlink()
        except OSError:
            pass
        raise


def _extract_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    dest_path: Path,
    passwords: list[bytes],
    state: dict,
) -> None:
    """파일 하나를 푼다. 암호가 걸렸으면 비밀번호 후보(UTF-8, cp949)를 차례로 해 본다.
    맞는 비밀번호를 찾으면 state['pwd'] 에 기억해 다음 파일에 먼저 쓴다."""
    if info.compress_type not in SUPPORTED_COMPRESSION:
        raise ZipExtractError(REASON_UNSUPPORTED)
    if not info.flag_bits & 0x1:
        _copy_member(archive, info, dest_path, None)
        return
    if not passwords:
        raise ZipExtractError(REASON_NEED_PASSWORD)
    known = state.get("pwd")
    order = ([known] if known else []) + [pwd for pwd in passwords if pwd != known]
    reason = REASON_BAD_PASSWORD
    for pwd in order:
        try:
            _copy_member(archive, info, dest_path, pwd)
        except RuntimeError as exc:
            if "password" in str(exc).lower():
                continue
            raise
        except (zipfile.BadZipFile, zlib.error, EOFError, *_LZMA_ERRORS):
            # 옛 ZIP 암호는 틀린 비밀번호를 1/256 확률로 통과시켜, 풀다가 깨진 데이터로 드러난다.
            reason = REASON_BAD_PASSWORD_OR_CORRUPT
            continue
        state["pwd"] = pwd
        return
    raise ZipExtractError(reason)


def _member_error_reason(exc: Exception, encrypted: bool) -> str:
    if isinstance(exc, ZipExtractError):
        return str(exc)
    if isinstance(exc, NotImplementedError):
        return REASON_UNSUPPORTED
    if isinstance(exc, (zipfile.BadZipFile, zlib.error, EOFError, *_LZMA_ERRORS)):
        # 옛 ZIP 암호는 틀린 비밀번호를 1/256 확률로 통과시켜, 풀다가 깨진 데이터로 드러난다.
        return REASON_BAD_PASSWORD_OR_CORRUPT if encrypted else REASON_CORRUPT
    return f"풀지 못했습니다 ({exc})"


def _main_reason(reasons: list[str]) -> str:
    """여러 파일의 이유 중 가장 많이 나온 것."""
    counts: dict[str, int] = {}
    for reason in reasons:
        counts[reason] = counts.get(reason, 0) + 1
    return max(counts, key=lambda key: counts[key]) if counts else ""


def _remove_empty_created(folders: list[Path], keep: set[Path]) -> None:
    """이번에 만든 폴더 중 비어 있는 것을 안쪽부터 지운다(keep 에 든 폴더는 둔다)."""
    for folder in sorted(set(folders), key=lambda path: len(path.parts), reverse=True):
        if folder in keep:
            continue
        try:
            folder.rmdir()
        except OSError:
            pass


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
    """ZIP 안 파일 이름을 읽는다.

    UTF-8 표시가 있으면 그대로 쓴다. 표시가 없으면 파이썬이 cp437 로 읽어 두므로 원래 바이트로
    되돌린 뒤 UTF-8(맥에서 만든 ZIP 은 표시 없이 UTF-8 로 적는다) → cp949(윈도 한글) 순서로 읽고,
    둘 다 아니면 원래(cp437) 이름을 쓴다.
    """
    name = info.filename
    if info.flag_bits & 0x800:
        return name

    try:
        raw = name.encode("cp437")
    except UnicodeEncodeError:
        return name
    for encoding in ("utf-8", "cp949"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
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

    # 폴더를 만들기 전에 ZIP 을 먼저 열어 본다. 손상된 파일이면 빈 폴더를 남기지 않는다.
    try:
        archive = zipfile.ZipFile(zip_file, "r")
    except (zipfile.BadZipFile, EOFError) as exc:
        raise ZipExtractError(REASON_CORRUPT) from exc

    created: list[Path] = []
    explicit_dirs: set[Path] = set()

    def ensure_dir(path: Path) -> None:
        missing = []
        current = path
        while not current.exists() and current != current.parent:
            missing.append(current)
            current = current.parent
        path.mkdir(parents=True, exist_ok=True)
        created.extend(missing)

    if extract_mode == EXTRACT_TO_NAMED_FOLDER:
        target_folder = make_unique_folder_path(base_output / safe_name(zip_stem_name(zip_file)))
        ensure_dir(target_folder)
    else:
        target_folder = base_output

    result.target_folder = target_folder
    target_abs = target_folder.resolve()
    passwords = password_candidates(password_text)
    password_state: dict = {}

    with archive:
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
                    ensure_dir(dest_path)
                    explicit_dirs.add(dest_path)
                    result.folder_count += 1
                    continue

                ensure_dir(dest_path.parent)
                dest_path = make_unique_file_path(dest_path)

                _extract_member(archive, info, dest_path, passwords, password_state)

                try:
                    modified = datetime(*info.date_time)
                    timestamp = modified.timestamp()
                    os.utime(dest_path, (timestamp, timestamp))
                except Exception:
                    pass

                result.file_count += 1
            except Exception as exc:
                reason = _member_error_reason(exc, bool(info.flag_bits & 0x1))
                result.error_count += 1
                result.reasons.append(reason)
                result.errors.append(f"{decode_zip_member_name(info)}: {reason}")

    if result.file_count == 0 and result.error_count:
        # 하나도 못 풀었다: ZIP 자체가 실패. 이번에 만든 폴더를 모두 치운다.
        _remove_empty_created(created, keep=set())
        raise ZipExtractError(_main_reason(result.reasons))
    # 풀지 못한 파일 때문에 만들어 두고 비어 버린 폴더를 치운다(ZIP 안에 원래 있던 빈 폴더는 둔다).
    _remove_empty_created(created, keep=explicit_dirs | {target_folder})

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
                batch.failed.append({
                    "name": Path(zip_file).name,
                    "error": f"파일 {result.error_count}개를 풀지 못했습니다 — {_main_reason(result.reasons)}",
                })
                for error in result.errors[:5]:
                    log(f"    ! {error}")
                if len(result.errors) > 5:
                    log(f"    ! 추가 오류 {len(result.errors) - 5}건 생략")
        except Exception as exc:
            batch.fail_count += 1
            batch.total_errors += 1
            reason = str(exc) if isinstance(exc, ZipExtractError) else f"풀지 못했습니다 ({exc})"
            batch.failed.append({"name": Path(zip_file).name, "error": reason})
            log(f"  ! 실패: {reason}")
        log()

    log("===== 완료 =====")
    log(f"성공 ZIP: {batch.success_count}개")
    log(f"실패 ZIP: {batch.fail_count}개")
    log(f"압축 해제 파일: {batch.total_files}개")
    log(f"오류: {batch.total_errors}개")
    return batch
