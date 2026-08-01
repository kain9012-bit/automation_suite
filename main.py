from __future__ import annotations

import sys

from app.self_update import run_update_helper
from app.tk_main_window import run_app


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--apply-update":
        return run_update_helper(sys.argv[2:])
    return run_app()


if __name__ == "__main__":
    raise SystemExit(main())
