"""Integration tests for publisher tier admission and capability attachment."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Import the block init functions under test.
from app.blocks import _build_block_caps, _validate_registry_block
from app.blocks import _EXTENDED_BLOCK_DEFS as _REAL_EXTENDED_BLOCK_DEFS
from app.core.block_capabilities import BlockCapabilities
from app.core.block_validation import BlockValidator
from app.core.publisher_registry import BlockSigner, PublisherRegistry


def _make_registry_block(tmp_path: Path, name: str, publisher_id: str, tier: str | None):
    registry_root = tmp_path / "block_registry"
    block_dir = registry_root / name
    block_dir.mkdir(parents=True)
    manifest = {
        "id": name,
        "name": name,
        "version": "1.0.0",
        "publisher_id": publisher_id,
        "permissions": {
            "network": False,
            "filesystem": False,
            "imports": [],
            "blocks": [],
        },
    }
    (block_dir / "block.json").write_text(json.dumps(manifest), encoding="utf-8")
    (block_dir / "block.py").write_text("def run(inputs):\n    return {'result': 'ok'}\n", encoding="utf-8")
    return registry_root


def test_build_block_caps_assigns_reviewed_tier(tmp_path: Path):
    pub_registry = PublisherRegistry(path=tmp_path / "publishers.json")
    pub_registry.register(
        publisher_id="reviewed_pub",
        name="Reviewed Pub",
        contact="v@example.com",
        public_key=__import__("base64").b64encode(__import__("os").urandom(32)).decode(),
        tier="reviewed",
    )
    registry_root = _make_registry_block(tmp_path, "reviewed_block", "reviewed_pub", None)

    validator = BlockValidator(
        publisher_registry=pub_registry,
        certification_store_path=tmp_path / "certs.json",
    )

    # Build a minimal defs dict for the one non-core block.
    defs = {"reviewed_block": ("app.blocks.not_real", "NotReal")}
    with patch("app.blocks._REGISTRY_ROOT", registry_root), \
         patch("app.blocks._is_core_block", return_value=False):
        caps = _build_block_caps(defs, validator=validator)

    assert caps["reviewed_block"].publisher_tier == "reviewed"
    assert caps["reviewed_block"].must_run_out_of_process is False


def test_build_block_caps_defaults_unknown_to_community(tmp_path: Path):
    registry_root = _make_registry_block(tmp_path, "unknown_block", "unknown_pub", None)
    defs = {"unknown_block": ("app.blocks.not_real", "NotReal")}

    with patch("app.blocks._REGISTRY_ROOT", registry_root), \
         patch("app.blocks._is_core_block", return_value=False):
        caps = _build_block_caps(defs)

    assert caps["unknown_block"].publisher_tier == "community"
    assert caps["unknown_block"].must_run_out_of_process is True


def test_validate_registry_block_excludes_revoked_publisher(
    tmp_path: Path,
):
    """A non-core registry block whose publisher is revoked is excluded."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    import base64

    private_key = Ed25519PrivateKey.generate()
    raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_key_b64 = base64.b64encode(raw).decode("ascii")

    pub_registry = PublisherRegistry(path=tmp_path / "publishers.json")
    pub_registry.register(
        publisher_id="revoked_pub",
        name="Revoked Pub",
        contact="r@example.com",
        public_key=public_key_b64,
        tier="reviewed",
    )
    pub_registry.revoke("revoked_pub")

    registry_root = _make_registry_block(tmp_path, "revoked_block", "revoked_pub", None)
    block_dir = registry_root / "revoked_block"
    BlockSigner.sign_block(
        block_path=block_dir,
        publisher_id="revoked_pub",
        private_key=private_key,
    )

    validator = BlockValidator(
        publisher_registry=pub_registry,
        certification_store_path=tmp_path / "certs.json",
    )

    with patch("app.blocks._REGISTRY_ROOT", registry_root):
        admitted = _validate_registry_block(
            "revoked_block",
            validator,
            require_capabilities=False,
        )
    assert admitted is False


def test_platform_extended_block_uses_registry_tier(tmp_path: Path):
    """Platform extended blocks with the platform publisher_id inherit its certified tier."""
    registry_root = _make_registry_block(tmp_path, "local_drive", "cerebrum_platform", None)
    defs = {"local_drive": _REAL_EXTENDED_BLOCK_DEFS["local_drive"]}

    with patch("app.blocks._REGISTRY_ROOT", registry_root), \
         patch("app.blocks._is_core_block", return_value=False), \
         patch("app.blocks._EXTENDED_BLOCK_DEFS", {"local_drive": defs["local_drive"]}):
        caps = _build_block_caps(defs)

    assert caps["local_drive"].publisher_tier == "certified"
    assert caps["local_drive"].must_run_out_of_process is False


def test_kit_block_without_publisher_defaults_to_community(tmp_path: Path):
    """A third-party kit block with no declared publisher is sandboxed by default."""
    registry_root = _make_registry_block(tmp_path, "kit_block", "", None)
    # Ensure no publisher_id key is in the manifest.
    manifest_path = registry_root / "kit_block" / "block.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("publisher_id", None)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    defs = {"kit_block": ("app.blocks.not_real", "NotReal")}
    with patch("app.blocks._REGISTRY_ROOT", registry_root), \
         patch("app.blocks._is_core_block", return_value=False):
        caps = _build_block_caps(defs)

    assert caps["kit_block"].publisher_tier == "community"
    assert caps["kit_block"].must_run_out_of_process is True
