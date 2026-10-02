"""한글 용량 압축 — 옛 한글(hwp)을 hwpx 로 바꾸기.

그림을 줄이는 일은 hwpx(ZIP) 안에서만 할 수 있다. hwp 는 한컴 전용 이진 형식이라, PC 에 설치된
한글로 임시 hwpx 를 만든 뒤 그것을 줄인다. 결과는 hwpx 로 저장한다.

- 원본 hwp 는 건드리지 않는다(임시 폴더에 복사한 것을 연다).
- 한글은 늦은 바인딩(dynamic)으로만 부른다. gen_py 캐시가 망가진 PC 에서도 동작하게 하려는 것이다.
- 파일 접근 허락 창을 막는 보안 모듈을 여러 이름으로 시도하고, 하나도 없으면 한글 창을 보여 준다.
  숨긴 채로 두면 '접근 허용' 창도 숨어 누를 사람이 없고 작업이 끝나지 않는다.
- 여러 파일을 바꿀 때는 한글을 한 번만 띄우고, 끝나면(오류가 나도) 반드시 끈다.
- 다른 도구의 코드는 불러 쓰지 않는다. 다른 도구를 고쳐도 이 도구가 깨지지 않게 하려는 것이다.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Callable, Optional

OLE_MAGIC = b"\xd0\xcf\x11\xe0"
ALLOW_HINT = "한글이 파일 접근을 물으면 [허용]을 눌러 주세요."
NO_HANCOM = "옛 한글(hwp) 파일은 한글 프로그램으로 hwpx 로 바꾼 뒤 줄이는데, 이 PC 에서 한글을 부를 수 없습니다."


class HancomError(Exception):
    pass


def is_old_hwp(path: Path) -> bool:
    """내부가 옛 한글(OLE) 형식인지. 확장자가 hwpx 여도 속이 hwp 인 파일이 있다."""
    try:
        with open(path, "rb") as f:
            return f.read(4) == OLE_MAGIC
    except OSError:
        return False


class HancomConverter:
    """hwp → hwpx 변환기. 처음 변환할 때 한글을 띄우고 close() 에서 끈다."""

    def __init__(self, progress: Optional[Callable[[str], None]] = None):
        self._progress = progress
        self._hwp = None
        self._pythoncom = None
        self._work = Path(tempfile.mkdtemp(prefix="jbedu_hcz_hwp_"))

    def _say(self, text: str) -> None:
        if self._progress is not None:
            try:
                self._progress(text)
            except Exception:
                pass

    def _start(self):
        if self._hwp is not None:
            return self._hwp
        try:
            import pythoncom
            import win32com.client.dynamic
        except Exception as exc:
            raise HancomError(NO_HANCOM) from exc
        pythoncom.CoInitialize()
        self._pythoncom = pythoncom
        errors = []
        for pid in ("HWPFrame.HwpObject", "HwpFrame.HwpObject", "HWPFrame.HwpObject.1", "HwpFrame.HwpObject.1"):
            try:
                self._hwp = win32com.client.dynamic.Dispatch(pid)
                break
            except Exception as exc:
                errors.append(str(exc))
        if self._hwp is None:
            raise HancomError(
                "옛 한글(hwp) 파일을 줄이려면 한글 프로그램이 필요합니다. 한글이 설치되어 있는지 확인해 주세요.\n"
                f"(내부 오류: {errors[-1] if errors else ''})"
            )
        if self._register_security():
            self._set_visible(False)
        else:
            self._set_visible(True)
            self._say(ALLOW_HINT)
        return self._hwp

    def _register_security(self) -> bool:
        names = [os.environ.get("HWP_FILE_PATH_CHECKER_MODULE", "").strip(), "SecurityModule",
                 "FilePathCheckerModule", "FilePathCheckerModuleExample"]
        tried = set()
        for name in names:
            if not name or name in tried:
                continue
            tried.add(name)
            try:
                if self._hwp.RegisterModule("FilePathCheckDLL", name):
                    return True
            except Exception:
                continue
        return False

    def _set_visible(self, visible: bool) -> None:
        try:
            self._hwp.XHwpWindows.Item(0).Visible = visible
        except Exception:
            pass

    def convert(self, src: Path, dst: Path) -> None:
        """src(hwp)를 hwpx 로 바꿔 dst 에 쓴다. 원본은 복사본으로만 연다."""
        hwp = self._start()
        tmp_in = self._work / f"input{src.suffix.lower() or '.hwp'}"
        tmp_out = self._work / "output.hwpx"
        for p in (tmp_in, tmp_out):
            try:
                p.unlink()
            except OSError:
                pass
        shutil.copy2(src, tmp_in)
        try:
            errors = []
            opened = False
            for fmt, option in (("", ""), ("HWP", ""), ("HWP", "forceopen:true"), ("", "forceopen:true")):
                try:
                    if hwp.Open(str(tmp_in), fmt, option) is False:
                        errors.append(f"Open False ({fmt}, {option})")
                        continue
                    opened = True
                    break
                except Exception as exc:
                    errors.append(str(exc))
            if not opened:
                raise HancomError("한글에서 파일을 열지 못했습니다: " + " | ".join(errors[-2:]))

            errors = []
            saved = False
            for fmt in ("HWPX", "HWPXDocument"):
                try:
                    if hwp.SaveAs(str(tmp_out), fmt, "") is False:
                        errors.append(f"SaveAs False ({fmt})")
                        continue
                    if tmp_out.exists() and tmp_out.stat().st_size > 0:
                        saved = True
                        break
                except Exception as exc:
                    errors.append(str(exc))
            if not saved:
                raise HancomError("한글에서 hwpx 로 저장하지 못했습니다: " + " | ".join(errors[-2:]))
            # 제대로 된 hwpx(ZIP)인지 확인한 뒤에만 쓴다.
            with open(tmp_out, "rb") as f:
                if f.read(2) != b"PK":
                    raise HancomError("한글이 만든 hwpx 가 올바르지 않습니다.")
            part = dst.with_name(dst.name + ".part")
            shutil.copyfile(tmp_out, part)
            part.replace(dst)
        finally:
            # 다음 파일을 열기 전에 문서를 비운다(저장 여부를 묻지 않음).
            try:
                hwp.Clear(1)
            except Exception:
                pass

    def close(self) -> None:
        """한글을 끈다. 끄지 않으면 프로세스가 남아 파일을 붙잡는다."""
        hwp, self._hwp = self._hwp, None
        if hwp is not None:
            for call in (lambda: hwp.Clear(1), lambda: hwp.Quit()):
                try:
                    call()
                except Exception:
                    pass
        hwp = None
        if self._pythoncom is not None:
            try:
                self._pythoncom.CoUninitialize()
            except Exception:
                pass
            self._pythoncom = None
        shutil.rmtree(self._work, ignore_errors=True)
