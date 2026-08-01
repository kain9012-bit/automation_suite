from __future__ import annotations

import os
import sys
from pathlib import Path


class SettingsService:
    @staticmethod
    def _startup_folder() -> Path:
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        return Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"

    @classmethod
    def _startup_script_path(cls, base_dir: Path) -> Path:
        if getattr(sys, "frozen", False):
            script_name = f"{Path(sys.executable).stem}_start.cmd"
        else:
            script_name = f"{base_dir.resolve().name}_start.cmd"
        return cls._startup_folder() / script_name

    @classmethod
    def _legacy_script_path(cls) -> Path:
        return cls._startup_folder() / "automation_suite_start.cmd"

    @staticmethod
    def _launch_target(base_dir: Path) -> str:
        if getattr(sys, "frozen", False):
            return f'"{Path(sys.executable).resolve()}"'
        main_py = (base_dir / "main.py").resolve()
        return f'"{sys.executable}" "{main_py}"'

    @classmethod
    def set_windows_auto_start(cls, enabled: bool, base_dir: Path) -> tuple[bool, str]:
        try:
            startup_dir = cls._startup_folder()
            startup_dir.mkdir(parents=True, exist_ok=True)
            script_path = cls._startup_script_path(base_dir)
            legacy_path = cls._legacy_script_path()

            if enabled:
                launch_target = cls._launch_target(base_dir)
                script = "@echo off\n"
                script += f'cd /d "{str(base_dir.resolve())}"\n'
                script += f'start "" {launch_target}\n'
                script_path.write_text(script, encoding="utf-8")
                if legacy_path.exists() and legacy_path != script_path:
                    legacy_path.unlink()
                return True, "컴퓨터 시작 시 자동 실행이 설정되었습니다."

            for path in {script_path, legacy_path}:
                if path.exists():
                    path.unlink()
            return True, "컴퓨터 시작 시 자동 실행이 해제되었습니다."
        except Exception as exc:
            return False, f"Windows 시작프로그램 설정을 변경하지 못했습니다.\n\n{exc}"

    @classmethod
    def is_windows_auto_start_enabled(cls, base_dir: Path) -> bool:
        try:
            return cls._startup_script_path(base_dir).exists() or cls._legacy_script_path().exists()
        except Exception:
            return False
