from __future__ import annotations

import argparse
import base64
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=".signing/tools_ed25519")
    args = parser.parse_args()

    prefix = Path(args.output).resolve()
    prefix.parent.mkdir(parents=True, exist_ok=True)
    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        Encoding.Raw,
        PrivateFormat.Raw,
        NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        Encoding.Raw,
        PublicFormat.Raw,
    )
    prefix.with_suffix(".key").write_text(
        base64.b64encode(private_bytes).decode("ascii"),
        encoding="ascii",
    )
    prefix.with_suffix(".pub").write_text(
        base64.b64encode(public_bytes).decode("ascii"),
        encoding="ascii",
    )
    print(prefix.with_suffix(".pub"))


if __name__ == "__main__":
    main()

