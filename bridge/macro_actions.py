from __future__ import annotations

import ctypes
import os
import shlex
import subprocess
import time
import webbrowser
from pathlib import Path


class MacroActionError(RuntimeError):
    pass


def run_action(action: dict) -> dict:
    action_type = str(action.get("type", "")).strip()
    if action_type == "macro":
        steps = action.get("steps", [])
        if not isinstance(steps, list) or not steps:
            raise MacroActionError("매크로 단계를 하나 이상 추가해 주세요.")
        for step in steps:
            run_action(step)
        return {"ok": True, "message": f"{len(steps)}단계 매크로를 실행했습니다."}
    if action_type == "site":
        target = _target(action)
        webbrowser.open(target if "://" in target else f"https://{target}")
    elif action_type in {"folder", "file"}:
        target = _expanded(_target(action))
        if not Path(target).exists():
            raise MacroActionError(f"경로를 찾을 수 없습니다.\n{target}")
        os.startfile(target)
    elif action_type == "program":
        target = _expanded(_target(action))
        if not Path(target).exists():
            raise MacroActionError(f"프로그램을 찾을 수 없습니다.\n{target}")
        arguments = str(action.get("arguments", "")).strip()
        if arguments:
            subprocess.Popen([target, *shlex.split(arguments, posix=False)])
        else:
            os.startfile(target)
    elif action_type == "command":
        subprocess.Popen(_target(action), shell=True, creationflags=0x08000000)
    elif action_type == "hotkey":
        _press_hotkey(_target(action))
    elif action_type == "text":
        _copy_text(_target(action))
        _press_hotkey("ctrl+v")
    elif action_type == "wait":
        try:
            seconds = float(_target(action))
        except ValueError as error:
            raise MacroActionError("대기 시간은 숫자로 입력해 주세요.") from error
        if seconds < 0 or seconds > 3600:
            raise MacroActionError("대기 시간은 0초에서 3600초 사이로 입력해 주세요.")
        time.sleep(seconds)
    else:
        raise MacroActionError("지원하지 않는 빠른 실행 동작입니다.")
    return {"ok": True, "message": f"{action.get('name', '빠른 실행')} 실행을 완료했습니다."}


def _target(action: dict) -> str:
    target = str(action.get("target", "")).strip()
    if not target:
        raise MacroActionError("실행할 주소나 경로를 입력해 주세요.")
    return target


def _expanded(value: str) -> str:
    return str(Path(os.path.expandvars(os.path.expanduser(value))))


def _press_hotkey(value: str) -> None:
    keys = [_normalize_key(part) for part in value.replace(",", "+").split("+") if part.strip()]
    if not keys:
        raise MacroActionError("단축키를 입력해 주세요.")
    codes = [_virtual_key_code(key) for key in keys]
    user32 = ctypes.windll.user32
    for code in codes:
        user32.keybd_event(code, 0, 0, 0)
        time.sleep(0.02)
    for code in reversed(codes):
        user32.keybd_event(code, 0, 0x0002, 0)
        time.sleep(0.02)


def _normalize_key(key: str) -> str:
    lowered = key.strip().lower()
    return {"control": "ctrl", "ctl": "ctrl", "windows": "win", "cmd": "win", "esc": "escape", "return": "enter", "del": "delete", "pgup": "pageup", "pgdn": "pagedown"}.get(lowered, lowered)


def _virtual_key_code(key: str) -> int:
    codes = {"ctrl": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B, "enter": 0x0D, "escape": 0x1B, "tab": 0x09, "space": 0x20, "backspace": 0x08, "delete": 0x2E, "insert": 0x2D, "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27}
    if key in codes:
        return codes[key]
    if len(key) == 1 and key.isalpha():
        return ord(key.upper())
    if len(key) == 1 and key.isdigit():
        return ord(key)
    if key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        return 0x70 + int(key[1:]) - 1
    raise MacroActionError(f"지원하지 않는 단축키입니다: {key}")


def _copy_text(text: str) -> None:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.restype = ctypes.c_void_p
    user32.SetClipboardData.restype = ctypes.c_void_p
    data = (text + "\0").encode("utf-16-le")
    handle = None
    if not user32.OpenClipboard(None):
        raise MacroActionError("클립보드를 열 수 없습니다.")
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(0x0002, len(data))
        locked = kernel32.GlobalLock(handle)
        ctypes.memmove(locked, data, len(data))
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(13, handle):
            raise MacroActionError("클립보드에 텍스트를 넣지 못했습니다.")
        handle = None
    finally:
        user32.CloseClipboard()
        if handle:
            kernel32.GlobalFree(handle)
