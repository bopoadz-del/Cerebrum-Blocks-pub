#!/usr/bin/env python3
"""Sign a block folder with a publisher's Ed25519 private key."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add project root so app imports work when run from scripts/.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.publisher_registry import BlockSigner, _load_private_key


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sign a block folder and write signature/digests to block.json."
    )
    parser.add_argument("--block", required=True, type=Path, help="Path to block folder")
    parser.add_argument("--publisher", required=True, help="Publisher ID")
    parser.add_argument("--key", required=True, type=Path, help="Path to PEM private key")
    args = parser.parse_args()

    block_path = Path(args.block)
    manifest_path = block_path / "block.json"
    if not manifest_path.exists():
        print(f"Error: block manifest not found: {manifest_path}", file=sys.stderr)
        return 1

    private_key = _load_private_key(args.key)
    result = BlockSigner.sign_block(
        block_path=block_path,
        publisher_id=args.publisher,
        private_key=private_key,
    )

    print(f"Signed block: {block_path}")
    print(f"Publisher:    {result['publisher_id']}")
    print(f"Signature:    {result['signature']}")
    print("Digests:")
    print(json.dumps(result["digests"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
