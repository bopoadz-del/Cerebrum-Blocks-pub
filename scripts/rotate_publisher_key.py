#!/usr/bin/env python3
"""Register/rotate a publisher key and re-sign that publisher's registry blocks.

Steps:
1. Resolve the publisher: ``--publisher`` if given; otherwise the single
   publisher in data/publishers.json. With zero or several registered
   publishers and no ``--publisher``, the script refuses (exit 2).
2. Resolve the public key: from ``--public-key FILE`` (base64 raw Ed25519 as
   written by scripts/generate_publisher_key.py, or a PEM public key) and/or
   derived from the private key. If both are given they must match.
3. Create the registry entry when data/publishers.json or the publisher is
   absent; update the public key when present (PublisherRegistry.register,
   which keeps created_at). Write data/publishers/<publisher>.pub.
4. With a private key (``--private-key`` or a new ``--private-key-out``):
   re-sign every block_registry/*/block.json whose publisher_id is this
   publisher (or which has no publisher_id yet), then verify EVERY block.

The PRIVATE key is read from / written to a path OUTSIDE the repository
only. It is never committed and never printed.

Usage:
  python scripts/rotate_publisher_key.py --private-key-out /secure/key.pem [--publisher ID]
  python scripts/rotate_publisher_key.py --private-key /secure/key.pem [--publisher ID]
  python scripts/rotate_publisher_key.py --public-key ID.pub --publisher ID   # register only
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # noqa: E402
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from app.core.publisher_registry import (  # noqa: E402
    BlockSigner,
    BlockVerifier,
    PublisherRegistry,
    _load_private_key,
)


class RotateError(Exception):
    """A refusal that maps to exit code 2."""


def _raw_b64(public_key: Ed25519PublicKey) -> str:
    raw = public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode("ascii")


def read_public_key_file(path: Path) -> str:
    """Return the base64 raw Ed25519 public key held in ``path`` (b64 or PEM)."""
    data = path.read_bytes().strip()
    if data.startswith(b"-----BEGIN"):
        key = serialization.load_pem_public_key(data)
        if not isinstance(key, Ed25519PublicKey):
            raise RotateError(f"{path} is not an Ed25519 public key")
        return _raw_b64(key)
    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(data, validate=True))
    except Exception as exc:
        raise RotateError(f"{path} is not a base64 Ed25519 public key: {exc}") from exc
    return _raw_b64(key)


def resolve_publisher(registry: PublisherRegistry, requested: str | None) -> str:
    """``requested`` if given, else the only registered publisher."""
    if requested:
        return requested
    ids = registry.publisher_ids()
    if len(ids) == 1:
        return ids[0]
    if not ids:
        raise RotateError(
            f"no publisher registered in {registry.path}; pass --publisher ID"
        )
    raise RotateError(f"several publishers registered {ids}; pass --publisher ID")


def upsert_publisher(
    registry: PublisherRegistry,
    publisher_id: str,
    public_b64: str,
    name: str | None,
    contact: str | None,
    tier: str | None,
) -> str:
    """Create or update the registry entry; return 'created' or 'updated'."""
    existing = registry.get(publisher_id)
    registry.register(
        publisher_id=publisher_id,
        name=name or (existing.name if existing else publisher_id),
        contact=contact if contact is not None else (existing.contact if existing else ""),
        public_key=public_b64,
        tier=tier or (existing.tier if existing else "community"),
    )
    return "updated" if existing else "created"


def resign_blocks(
    registry_root: Path, publisher_id: str, private_key: Ed25519PrivateKey
) -> list[str]:
    """Sign blocks owned by ``publisher_id`` (or unowned); return their names."""
    signed = []
    for block_dir in sorted(p for p in registry_root.iterdir() if p.is_dir()):
        manifest_path = block_dir / "block.json"
        if not manifest_path.exists():
            continue
        owner = json.loads(manifest_path.read_text(encoding="utf-8")).get("publisher_id")
        if owner not in (None, "", publisher_id):
            continue
        BlockSigner.sign_block(
            block_path=block_dir, publisher_id=publisher_id, private_key=private_key
        )
        signed.append(block_dir.name)
    return signed


def verify_all(
    registry_root: Path, registry: PublisherRegistry
) -> list[tuple[str, str | None]]:
    """Verify every block dir; return (name, reason) for each failure."""
    verifier = BlockVerifier(registry=registry)
    failures = []
    for block_dir in sorted(p for p in registry_root.iterdir() if p.is_dir()):
        if not (block_dir / "block.json").exists():
            continue
        result = verifier.verify_block(block_dir)
        if not result.get("verified"):
            failures.append((block_dir.name, result.get("reason")))
    return failures


def run(argv: list[str] | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--private-key-out", type=Path, help="Write a NEW private key here (outside the repo)")
    group.add_argument("--private-key", type=Path, help="Reuse an existing PEM private key")
    parser.add_argument("--public-key", type=Path, help="Public key file (base64 raw or PEM)")
    parser.add_argument("--publisher", help="Publisher id (default: the single registered publisher)")
    parser.add_argument("--name", help="Publisher name when creating the entry (default: the id)")
    parser.add_argument("--contact", help="Publisher contact when creating the entry")
    parser.add_argument(
        "--tier",
        choices=["community", "reviewed", "certified"],
        help="Trust tier when creating (default: existing tier, else community)",
    )
    parser.add_argument("--registry", type=Path, help="Registry JSON (default: <root>/data/publishers.json)")
    parser.add_argument("--blocks", type=Path, help="Block registry dir (default: <root>/block_registry)")
    args = parser.parse_args(argv)

    root = Path(root).resolve()
    reg_path = args.registry or root / "data" / "publishers.json"
    blocks_root = args.blocks or root / "block_registry"

    try:
        if not (args.private_key_out or args.private_key or args.public_key):
            raise RotateError("give --private-key-out, --private-key, or --public-key")

        private_key: Ed25519PrivateKey | None = None
        if args.private_key_out:
            out = args.private_key_out.resolve()
            if out == root or root in out.parents:
                raise RotateError("--private-key-out must be OUTSIDE the repository")
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
            print(f"new private key written to {out}; store it in your secrets manager, then delete the file")
        elif args.private_key:
            private_key = _load_private_key(args.private_key)

        public_b64 = read_public_key_file(args.public_key) if args.public_key else None
        if private_key is not None:
            derived = _raw_b64(private_key.public_key())
            if public_b64 is not None and public_b64 != derived:
                raise RotateError("--public-key does not match the private key")
            public_b64 = derived

        registry = PublisherRegistry(path=reg_path)
        publisher_id = resolve_publisher(registry, args.publisher)
        action = upsert_publisher(
            registry, publisher_id, public_b64, args.name, args.contact, args.tier
        )
        key_dir = reg_path.parent / "publishers"
        key_dir.mkdir(parents=True, exist_ok=True)
        (key_dir / f"{publisher_id}.pub").write_text(public_b64 + "\n", encoding="utf-8")
        print(f"publisher {publisher_id}: registry entry {action} in {reg_path}")
    except RotateError as exc:
        print(f"refusing: {exc}", file=sys.stderr)
        return 2

    if private_key is None:
        return 0

    signed = resign_blocks(blocks_root, publisher_id, private_key)
    failures = verify_all(blocks_root, PublisherRegistry(path=reg_path))
    print(f"signed {len(signed)} blocks for {publisher_id}; verification failures: {len(failures)}")
    for name, reason in failures:
        print(f"  FAIL {name}: {reason}")
    return 1 if failures else 0


def main() -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())
