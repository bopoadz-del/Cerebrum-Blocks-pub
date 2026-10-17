"""Tests for publisher registry and Ed25519 block signing/verification."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core.publisher_registry import (
    BlockSigner,
    BlockVerifier,
    PublisherRegistry,
)


@pytest.fixture
def private_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


@pytest.fixture
def public_key_b64(private_key: Ed25519PrivateKey) -> str:
    raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    from app.core.publisher_registry import base64
    return base64.b64encode(raw).decode("ascii")


@pytest.fixture
def temp_registry(tmp_path: Path) -> PublisherRegistry:
    path = tmp_path / "publishers.json"
    return PublisherRegistry(path=path)


@pytest.fixture
def test_publisher(
    temp_registry: PublisherRegistry,
    public_key_b64: str,
):
    temp_registry.register(
        publisher_id="test_corp",
        name="Test Corp",
        contact="security@testcorp.example",
        public_key=public_key_b64,
        tier="reviewed",
    )
    return temp_registry


@pytest.fixture
def temp_block(tmp_path: Path) -> Path:
    block_path = tmp_path / "test_block"
    block_path.mkdir()
    (block_path / "block.json").write_text(
        json.dumps(
            {
                "id": "test_block",
                "name": "Test Block",
                "version": "1.0.0",
                "description": "A test block.",
                "inputs": [],
                "outputs": [],
            }
        ),
        encoding="utf-8",
    )
    (block_path / "block.py").write_text(
        "def run(inputs):\n    return {'result': 'ok'}\n",
        encoding="utf-8",
    )
    (block_path / "requirements.txt").write_text(
        "# test requirements\n",
        encoding="utf-8",
    )
    return block_path


def test_register_and_get_publisher(temp_registry: PublisherRegistry, public_key_b64: str):
    record = temp_registry.register(
        publisher_id="acme",
        name="Acme Blocks",
        contact="ops@acme.example",
        public_key=public_key_b64,
        tier="reviewed",
    )
    assert record.publisher_id == "acme"
    assert record.tier == "reviewed"
    assert record == temp_registry.get("acme")


def test_is_trusted_and_revoke(
    temp_registry: PublisherRegistry, public_key_b64: str
):
    temp_registry.register(
        publisher_id="acme",
        name="Acme Blocks",
        contact="ops@acme.example",
        public_key=public_key_b64,
        tier="reviewed",
    )
    assert temp_registry.is_trusted("acme") is True

    revoked = temp_registry.revoke("acme")
    assert revoked is not None
    assert revoked.tier == "revoked"
    assert temp_registry.is_trusted("acme") is False


def test_sign_and_verify_block(
    test_publisher: PublisherRegistry,
    temp_block: Path,
    private_key: Ed25519PrivateKey,
):
    BlockSigner.sign_block(
        block_path=temp_block,
        publisher_id="test_corp",
        private_key=private_key,
    )

    manifest = json.loads((temp_block / "block.json").read_text(encoding="utf-8"))
    assert manifest["publisher_id"] == "test_corp"
    assert "signature" in manifest
    assert "digests" in manifest
    assert set(manifest["digests"].keys()) == {"block.json", "block.py", "requirements.txt"}

    verifier = BlockVerifier(registry=test_publisher)
    result = verifier.verify_block(temp_block)
    assert result["verified"] is True
    assert result["publisher_id"] == "test_corp"
    assert result["reason"] is None


def test_verify_fails_after_tamper(
    test_publisher: PublisherRegistry,
    temp_block: Path,
    private_key: Ed25519PrivateKey,
):
    BlockSigner.sign_block(
        block_path=temp_block,
        publisher_id="test_corp",
        private_key=private_key,
    )

    block_py = temp_block / "block.py"
    block_py.write_text("# tampered\n", encoding="utf-8")

    verifier = BlockVerifier(registry=test_publisher)
    result = verifier.verify_block(temp_block)
    assert result["verified"] is False
    assert "digest mismatch" in result["reason"]


def test_verify_fails_when_revoked(
    test_publisher: PublisherRegistry,
    temp_block: Path,
    private_key: Ed25519PrivateKey,
):
    BlockSigner.sign_block(
        block_path=temp_block,
        publisher_id="test_corp",
        private_key=private_key,
    )
    test_publisher.revoke("test_corp")

    verifier = BlockVerifier(registry=test_publisher)
    result = verifier.verify_block(temp_block)
    assert result["verified"] is False
    assert "revoked" in result["reason"]


def test_verify_unknown_publisher(temp_block: Path):
    # No publisher registered.
    verifier = BlockVerifier(registry=PublisherRegistry(path=temp_block.parent / "publishers.json"))
    result = verifier.verify_block(temp_block)
    assert result["verified"] is False
    assert result["reason"] == "missing required field: publisher_id"


def test_registry_persistence(tmp_path: Path, public_key_b64: str):
    path = tmp_path / "publishers.json"
    registry = PublisherRegistry(path=path)
    registry.register(
        publisher_id="persist",
        name="Persist",
        contact="p@example.com",
        public_key=public_key_b64,
        tier="community",
    )

    # Load a fresh registry from the same file.
    registry2 = PublisherRegistry(path=path)
    record = registry2.get("persist")
    assert record is not None
    assert record.name == "Persist"
    assert record.tier == "community"
