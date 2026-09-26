"""문서 개인정보 마스킹 — 옛 한글(hwp)을 hwpx 로 바꿔 읽기.

hwp 는 한컴 전용 이진 형식이라 글자만 바꿔 넣으면 파일이 깨질 수 있다. 그래서 PC 에 설치된
한글로 hwpx 임시 사본을 만든 뒤, 그 사본을 hwpx 와 똑같이 처리한다. 결과 사본은 hwpx 로 저장한다.

- 원본 hwp 는 건드리지 않는다(임시 폴더에 복사한 것을 연다).
- 확인 화면에서 찾기(analyze)와 사본 만들기(apply)는 서로 다른 실행이라, 같은 임시 hwpx 를
  다시 쓰도록 원본의 경로·크기·수정 시각으로 이름을 정해 둔다. 원본이 바뀌면 이름도 바뀐다.
- 임시 hwpx 에는 개인정보가 그대로 있으므로 사본을 만든 뒤 지우고, 하루 넘은 것도 지운다.
- 한글은 늦은 바인딩(dynamic)으로만 부른다. gen_py 캐시가 망가진 PC 에서도 동작하게 하려는 것이다
  (한글 파일 취합 도구에서 겪은 문제). 다른 도구의 코드는 불러 쓰지 않는다.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import time
from pathlib import Path

OLE_MAGIC = b"\xd0\xcf\x11\xe0"
CACHE_DIR = Path(tempfile.gettempdir()) / "jbedu_dpm_hwp"
CACHE_HOURS = 24


class HancomError(Exception):
    pass


def is_old_hwp(path: Path) -> bool:
    """내부가 옛 한글(OLE) 형식인지. 확장자가 hwpx 여도 속이 hwp 인 파일이 있다."""
    try:
        with open(path, "rb") as f:
            return f.read(4) == OLE_MAGIC
    except OSError:
        return False


def cached_hwpx(path: Path) -> Path:
    st = path.stat()
    key = f"{path.resolve()}|{st.st_size}|{st.st_mtime_ns}"
    return CACHE_DIR / (hashlib.sha1(key.encode("utf-8")).hexdigest()[:20] + ".hwpx")


def cleanup_cache() -> None:
    if not CACHE_DIR.exists():
        return
    limit = time.time() - CACHE_HOURS * 3600
    for f in CACHE_DIR.glob("*"):
        try:
            if f.stat().st_mtime < limit:
                f.unlink()
        except OSError:
            pass


def forget(path: Path) -> None:
    """사본을 만든 뒤 그 원본의 임시 hwpx 를 지운다."""
    try:
        cached_hwpx(path).unlink()
    except OSError:
        pass


def working_hwpx(path: Path) -> Path:
    """옛 한글 파일이면 한글로 바꾼 임시 hwpx 경로를, 아니면 그대로 돌려준다."""
    if not is_old_hwp(path):
        return path
    cleanup_cache()
    target = cached_hwpx(path)
    if target.exists() and target.stat().st_size > 0:
        return target
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    convert_to_hwpx(path, target)
    return target


# ---------------------------------------------------------------- 한글 부르기

NO_HANCOM = "옛 한글(hwp) 형식 파일은 한글 프로그램으로 hwpx 로 바꿔 읽는데, 이 PC 에서 한글을 부를 수 없습니다."


def _hwp_object():
    import win32com.client.dynamic

    errors = []
    for pid in ("HWPFrame.HwpObject", "HwpFrame.HwpObject", "HWPFrame.HwpObject.1"):
        try:
            return win32com.client.dynamic.Dispatch(pid)
        except Exception as exc:
            errors.append(str(exc))
    raise HancomError("옛 한글(hwp) 파일을 열려면 한글 프로그램이 필요합니다. 한글이 설치되어 있는지 확인해 주세요.\n"
                      f"(내부 오류: {errors[-1] if errors else ''})")


def _register_security(hwp) -> None:
    # 한글이 파일 접근 허락 창을 띄우지 않게 하는 보안 모듈. 설치 방식마다 이름이 달라 여러 개를 시도한다.
    for name in (os.environ.get("HWP_FILE_PATH_CHECKER_MODULE", "").strip(), "SecurityModule",
                 "FilePathCheckerModule", "FilePathCheckerModuleExample"):
        if not name:
            continue
        try:
            if hwp.RegisterModule("FilePathCheckDLL", name):
                return
        except Exception:
            continue


def _open(hwp, src: str) -> None:
    errors = []
    for fmt, option in (("", ""), ("HWP", ""), ("HWP", "forceopen:true"), ("", "forceopen:true")):
        try:
            if hwp.Open(src, fmt, option) is False:
                errors.append(f"Open False ({fmt}, {option})")
                continue
            return
        except Exception as exc:
            errors.append(str(exc))
    raise HancomError("한글에서 파일을 열지 못했습니다: " + " | ".join(errors[-2:]))


def _save_hwpx(hwp, dst: str) -> None:
    errors = []
    for fmt in ("HWPX", "HWPXDocument"):
        try:
            hwp.SaveAs(dst, fmt, "")
            if os.path.exists(dst) and os.path.getsize(dst) > 0:
                return
        except Exception as exc:
            errors.append(str(exc))
    raise HancomError("한글에서 hwpx 로 저장하지 못했습니다: " + " | ".join(errors[-2:]))


def convert_to_hwpx(src: Path, dst: Path) -> None:
    try:
        import pythoncom
        import win32com.client.dynamic  # noqa: F401
    except Exception as exc:
        raise HancomError(NO_HANCOM) from exc

    work = Path(tempfile.mkdtemp(prefix="dpm_hwp_"))
    pythoncom.CoInitialize()
    hwp = None
    try:
        tmp_in = work / "input.hwp"
        tmp_out = work / "output.hwpx"
        shutil.copy2(src, tmp_in)
        hwp = _hwp_object()
        _register_security(hwp)
        try:
            hwp.XHwpWindows.Item(0).Visible = False
        except Exception:
            pass
        _open(hwp, str(tmp_in))
        _save_hwpx(hwp, str(tmp_out))
        # 제대로 된 hwpx(ZIP)인지 확인한 뒤에만 쓴다.
        with open(tmp_out, "rb") as f:
            if f.read(2) != b"PK":
                raise HancomError("한글이 만든 hwpx 가 올바르지 않습니다.")
        tmp_part = dst.with_name(dst.name + ".part")
        shutil.copyfile(tmp_out, tmp_part)
        tmp_part.replace(dst)
    finally:
        # 한글을 끝내지 않으면 프로세스가 남아 파일을 붙잡는다(한글 파일 취합과 같은 정리).
        if hwp is not None:
            for call in (lambda: hwp.Clear(1), lambda: hwp.Quit()):
                try:
                    call()
                except Exception:
                    pass
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass
        shutil.rmtree(work, ignore_errors=True)
