"""Block signing must be OPERATING: every registry block verifies.

The private signing key lives in AWS Secrets Manager (cerebrum/store-signing)
and the Store CI secret STORE_SIGNING_KEY -- never in the repository. The
public key is data/publishers.json. Rotation is scripts/rotate_publisher_key.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

import cryptography  # noqa: E402  (pinned in requirements.txt)


def _registry_blocks():
    for d in sorted((ROOT / "block_registry").iterdir()):
        if (d / "block.json").exists():
            yield d


def test_every_registry_block_is_signed_and_verifies():
    from app.core.publisher_registry import BlockVerifier

    verifier = BlockVerifier()
    unsigned, failed = [], []
    for block_dir in _registry_blocks():
        manifest = json.loads((block_dir / "block.json").read_text(encoding="utf-8"))
        if not manifest.get("signature"):
            unsigned.append(block_dir.name)
            continue
        result = verifier.verify_block(block_dir)
        if not result.get("verified"):
            failed.append((block_dir.name, result.get("reason")))
    assert not unsigned, f"unsigned blocks: {unsigned}"
    assert not failed, f"signature verification failures: {failed}"


def test_no_private_key_material_in_repo():
    hits = []
    for pattern in ("*.pem", "*.key"):
        hits.extend(
            p for p in ROOT.rglob(pattern)
            if ".git" not in p.parts and "node_modules" not in p.parts
        )
    private = []
    for p in hits:
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "PRIVATE KEY" in text:
            private.append(str(p))
    assert not private, f"private key material committed: {private}"
