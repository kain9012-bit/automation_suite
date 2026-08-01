from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("catalog", help="schema_version과 tools를 포함한 JSON")
    parser.add_argument("--private-key", default=".signing/tools_ed25519.key")
    parser.add_argument("--output", default="tool-catalog.signed.json")
    args = parser.parse_args()

    catalog_path = Path(args.catalog).resolve()
    payload_object = json.loads(catalog_path.read_text(encoding="utf-8"))
    payload = json.dumps(
        payload_object,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    private_bytes = base64.b64decode(
        Path(args.private_key).read_text(encoding="ascii").strip()
    )
    signature = Ed25519PrivateKey.from_private_bytes(private_bytes).sign(payload)
    envelope = {
        "payload": base64.b64encode(payload).decode("ascii"),
        "signature": base64.b64encode(signature).decode("ascii"),
    }
    Path(args.output).write_text(
        json.dumps(envelope, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

