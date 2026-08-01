from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path


def run_update_helper(args: list[str]) -> int:
    if len(args) != 3:
        return 2
    current = Path(args[0]).resolve()
    replacement = Path(args[1]).resolve()
    try:
        parent_pid = int(args[2])
    except ValueError:
        return 2

    for _ in range(120):
        try:
            os.kill(parent_pid, 0)
        except OSError:
            break
        time.sleep(0.25)

    backup = current.with_suffix(current.suffix + ".old")
    try:
        if backup.exists():
            backup.unlink()
        if current.exists():
            os.replace(current, backup)
        os.replace(replacement, current)
        subprocess.Popen([str(current)], cwd=str(current.parent))
        return 0
    except Exception:
        try:
            if not current.exists() and backup.exists():
                os.replace(backup, current)
        except Exception:
            pass
        return 1
