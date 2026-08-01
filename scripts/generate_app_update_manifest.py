from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("installer")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--notes", default="안정성 개선 및 도구 업데이트")
    parser.add_argument("--output", default="latest.json")
    args = parser.parse_args()

    installer = Path(args.installer).resolve()
    signature_path = Path(f"{installer}.sig")
    if not installer.is_file() or not signature_path.is_file():
        raise FileNotFoundError("설치 EXE와 같은 이름의 .sig 파일이 필요합니다.")

    manifest = {
        "version": args.version,
        "notes": args.notes,
        "pub_date": datetime.now(timezone.utc).isoformat(),
        "platforms": {
            "windows-x86_64": {
                "signature": signature_path.read_text(encoding="utf-8").strip(),
                "url": f"{args.base_url.rstrip('/')}/{installer.name}",
            }
        },
    }
    Path(args.output).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
