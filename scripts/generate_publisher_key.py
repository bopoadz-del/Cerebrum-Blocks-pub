#!/usr/bin/env python3
"""Generate an Ed25519 publisher key pair and optionally register the publisher."""

from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

# Add project root so app imports work when run from scripts/.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.publisher_registry import PublisherRegistry, DEFAULT_PUBLISHERS_KEY_DIR


def _generate_keypair() -> tuple[Ed25519PrivateKey, bytes, bytes]:
    """Generate a new Ed25519 key pair and return (private_key, pem, public_bytes)."""
    private_key = Ed25519PrivateKey.generate()
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return private_key, pem, public_bytes


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate an Ed25519 publisher key pair for block signing."
    )
    parser.add_argument("publisher_id", help="Unique publisher identifier")
    parser.add_argument("--name", help="Human-readable publisher name")
    parser.add_argument("--contact", help="Contact email or URL")
    parser.add_argument(
        "--tier",
        choices=("community", "reviewed", "certified", "revoked"),
        default="community",
        help="Trust tier (default: community)",
    )
    parser.add_argument(
        "--key-dir",
        type=Path,
        default=DEFAULT_PUBLISHERS_KEY_DIR,
        help=f"Directory to write key files (default: {DEFAULT_PUBLISHERS_KEY_DIR})",
    )
    parser.add_argument(
        "--register",
        action="store_true",
        help="Also register the publisher in data/publishers.json",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=None,
        help="Override path to publishers.json",
    )
    args = parser.parse_args()

    key_dir = Path(args.key_dir)
    key_dir.mkdir(parents=True, exist_ok=True)

    private_path = key_dir / f"{args.publisher_id}.key"
    public_path = key_dir / f"{args.publisher_id}.pub"

    if private_path.exists():
        print(f"Error: private key already exists: {private_path}", file=sys.stderr)
        return 1

    _, pem, public_bytes = _generate_keypair()
    public_b64 = base64.b64encode(public_bytes).decode("ascii")

    private_path.write_bytes(pem)
    private_path.chmod(0o600)
    public_path.write_text(public_b64 + "\n", encoding="utf-8")

    print(f"Private key: {private_path}")
    print(f"Public key:  {public_path}")
    print(f"Public key (base64): {public_b64}")

    if args.register:
        registry = PublisherRegistry(path=args.registry)
        registry.register(
            publisher_id=args.publisher_id,
            name=args.name or args.publisher_id,
            contact=args.contact or "",
            public_key=public_b64,
            tier=args.tier,
        )
        print(f"Registered publisher '{args.publisher_id}' in {registry.path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
