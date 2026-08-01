from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tool_dir")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output-dir", default="tool-packages")
    args = parser.parse_args()

    tool_dir = Path(args.tool_dir).resolve()
    manifest = json.loads((tool_dir / "manifest.json").read_text(encoding="utf-8"))
    tool_id = manifest["id"]
    version = manifest["version"]
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f"{tool_id}-{version}.zip"

    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in tool_dir.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            bundle.write(path, path.relative_to(tool_dir.parent))

    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    entry = {
        "id": tool_id,
        "name": manifest.get("name", tool_id),
        "version": version,
        "url": f"{args.base_url.rstrip('/')}/{archive.name}",
        "sha256": digest,
        "size": archive.stat().st_size,
    }
    print(json.dumps(entry, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

