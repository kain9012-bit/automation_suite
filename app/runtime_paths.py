from __future__ import annotations

import os
import sys
from pathlib import Path


APP_DATA_DIR_NAME = "JBEDUAutomationSuite"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent.parent


def executable_path() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve()
    return (resource_root() / "main.py").resolve()


def app_data_root() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if not base:
        base = str(Path.home())
    path = Path(base) / APP_DATA_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_tools_root() -> Path:
    path = app_data_root() / "tools"
    path.mkdir(parents=True, exist_ok=True)
    return path


def state_root() -> Path:
    path = app_data_root() / "config"
    path.mkdir(parents=True, exist_ok=True)
    return path


def updates_root() -> Path:
    path = app_data_root() / "updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def builtin_tools_root() -> Path:
    return resource_root() / "tools"


def bundled_apps_root() -> Path:
    return resource_root() / "bundled_apps"
