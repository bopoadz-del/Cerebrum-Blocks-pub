#!/usr/bin/env python3
"""Rotate the platform publisher key and re-sign every registry block.

Generates a fresh Ed25519 keypair, updates data/publishers.json and
data/publishers/<publisher>.pub, re-signs every block_registry/*/block.json,
and verifies 100% before exiting.

The PRIVATE key is written ONLY to --private-key-out, which must be OUTSIDE
the repository — store it in your secrets manager and delete the file.
It is never committed and never printed.

Usage:
  python scripts/rotate_publisher_key.py --private-key-out /secure/path/key.pem
  python scripts/rotate_publisher_key.py --private-key /secure/path/key.pem   # reuse existing
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core.publisher_registry import BlockSigner, BlockVerifier, _load_private_key

PUBLISHER_ID = "cerebrum_platform"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--private-key-out", type=Path, help="Write a NEW private key here (outside the repo)")
    group.add_argument("--private-key", type=Path, help="Reuse an existing PEM private key")
    args = parser.parse_args()

    if args.private_key_out:
        out = args.private_key_out.resolve()
        if str(out).startswith(str(ROOT)):
            print("refusing: --private-key-out must be OUTSIDE the repository", file=sys.stderr)
            return 2
        private_key = Ed25519PrivateKey.generate()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(
            private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        out.chmod(0o600)
        print(f"new private key written to {out} — store in your secrets manager, then delete the file")
    else:
        private_key = _load_private_key(args.private_key)

    public_raw = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    public_b64 = base64.b64encode(public_raw).decode("ascii")

    # Update the publisher registry with the new public key.
    reg_path = ROOT / "data" / "publishers.json"
    registry = json.loads(reg_path.read_text(encoding="utf-8"))
    for pub in registry["publishers"]:
        if pub["publisher_id"] == PUBLISHER_ID:
            pub["public_key"] = public_b64
            break
    else:
        print(f"publisher {PUBLISHER_ID} not found in {reg_path}", file=sys.stderr)
        return 2
    registry["updated_at"] = datetime.now(timezone.utc).isoformat()
    reg_path.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (ROOT / "data" / "publishers" / f"{PUBLISHER_ID}.pub").write_text(
        public_b64 + "\n", encoding="utf-8"
    )

    signed = 0
    for block_dir in sorted((ROOT / "block_registry").iterdir()):
        if not (block_dir / "block.json").exists():
            continue
        BlockSigner.sign_block(
            block_path=block_dir, publisher_id=PUBLISHER_ID, private_key=private_key
        )
        signed += 1

    verifier = BlockVerifier()
    failures = []
    for block_dir in sorted((ROOT / "block_registry").iterdir()):
        if not (block_dir / "block.json").exists():
            continue
        result = verifier.verify_block(block_dir)
        if not result.get("verified"):
            failures.append((block_dir.name, result.get("reason")))

    print(f"signed {signed} blocks; verification failures: {len(failures)}")
    for name, reason in failures:
        print(f"  FAIL {name}: {reason}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
