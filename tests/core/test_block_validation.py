"""Tests for the block validation gate and certification store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core.block_validation import (
    BlockValidationResult,
    BlockValidator,
    CertificationStore,
)
from app.core.publisher_registry import BlockSigner, PublisherRegistry


@pytest.fixture
def private_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


@pytest.fixture
def public_key_b64(private_key: Ed25519PrivateKey) -> str:
    raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    import base64

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


def _write_manifest(
    block_path: Path,
    extra: dict | None = None,
    remove: tuple[str, ...] = (),
) -> None:
    manifest = {
        "id": "test_block",
        "name": "Test Block",
        "version": "1.0.0",
        "description": "A test block.",
        "inputs": [],
        "outputs": [],
        "permissions": {
            "network": False,
            "filesystem": False,
            "imports": [],
            "blocks": [],
        },
        "trust_tier": "platform",
    }
    if extra:
        manifest.update(extra)
    for key in remove:
        manifest.pop(key, None)
    (block_path / "block.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )


@pytest.fixture
def temp_block(tmp_path: Path) -> Path:
    block_path = tmp_path / "test_block"
    block_path.mkdir()
    _write_manifest(block_path)
    (block_path / "block.py").write_text(
        "def run(inputs):\n    return {'result': 'ok'}\n",
        encoding="utf-8",
    )
    (block_path / "requirements.txt").write_text(
        "# test requirements\n",
        encoding="utf-8",
    )
    (block_path / "Dockerfile").write_text(
        "FROM python:3.11\n",
        encoding="utf-8",
    )
    return block_path


def test_passing_validation_for_signed_block(
    test_publisher: PublisherRegistry,
    temp_block: Path,
    private_key: Ed25519PrivateKey,
):
    BlockSigner.sign_block(
        block_path=temp_block,
        publisher_id="test_corp",
        private_key=private_key,
    )

    validator = BlockValidator(
        publisher_registry=test_publisher,
        certification_store_path=temp_block.parent / "certifications.json",
    )
    result = validator.validate_block(temp_block)

    assert result.status == "passed"
    assert result.block_id == "test_block"
    assert result.publisher_id == "test_corp"
    assert result.reasons == []
    assert validator.is_certified("test_block") is True


def test_signed_block_verifies_across_line_endings(
    test_publisher: PublisherRegistry,
    temp_block: Path,
    private_key: Ed25519PrivateKey,
):
    """Signatures produced on a CRLF checkout must verify on an LF checkout."""
    # Sign with CRLF line endings (typical of a Windows working tree).
    (temp_block / "block.py").write_bytes(
        b"def run(inputs):\r\n    return {'result': 'ok'}\r\n"
    )
    BlockSigner.sign_block(
        block_path=temp_block,
        publisher_id="test_corp",
        private_key=private_key,
    )

    # Simulate a Linux CI checkout: convert the source files to LF.
    (temp_block / "block.py").write_bytes(
        b"def run(inputs):\n    return {'result': 'ok'}\n"
    )
    if (temp_block / "Dockerfile").exists():
        (temp_block / "Dockerfile").write_bytes(
            b"FROM python:3.11\n"
        )

    validator = BlockValidator(
        publisher_registry=test_publisher,
        certification_store_path=temp_block.parent / "certifications.json",
    )
    result = validator.validate_block(temp_block)

    assert result.status == "passed"
    assert result.reasons == []


def test_validation_records_publisher_tier(
    test_publisher: PublisherRegistry,
    temp_block: Path,
    private_key: Ed25519PrivateKey,
    public_key_b64: str,
):
    test_publisher.register(
        publisher_id="test_corp",
        name="Test Corp",
        contact="security@testcorp.example",
        public_key=public_key_b64,
        tier="reviewed",
    )
    BlockSigner.sign_block(
        block_path=temp_block,
        publisher_id="test_corp",
        private_key=private_key,
    )
    validator = BlockValidator(
        publisher_registry=test_publisher,
        certification_store_path=temp_block.parent / "certifications.json",
    )
    result = validator.validate_block(temp_block)
    assert result.status == "passed"
    assert result.publisher_tier == "reviewed"


def test_revoked_publisher_fails_validation(
    test_publisher: PublisherRegistry,
    temp_block: Path,
    private_key: Ed25519PrivateKey,
    public_key_b64: str,
):
    test_publisher.register(
        publisher_id="test_corp",
        name="Test Corp",
        contact="security@testcorp.example",
        public_key=public_key_b64,
        tier="reviewed",
    )
    BlockSigner.sign_block(
        block_path=temp_block,
        publisher_id="test_corp",
        private_key=private_key,
    )
    test_publisher.revoke("test_corp")
    validator = BlockValidator(
        publisher_registry=test_publisher,
        certification_store_path=temp_block.parent / "certifications.json",
    )
    result = validator.validate_block(temp_block)
    assert result.status == "failed"
    assert result.publisher_tier == "revoked"
    assert any("revoked" in reason.lower() for reason in result.reasons)


def test_unknown_publisher_defaults_to_community_tier(
    temp_block: Path,
    private_key: Ed25519PrivateKey,
):
    """A publisher not in the registry defaults to community tier."""
    BlockSigner.sign_block(
        block_path=temp_block,
        publisher_id="unknown_pub",
        private_key=private_key,
    )
    validator = BlockValidator(
        publisher_registry=None,
        certification_store_path=temp_block.parent / "certifications.json",
    )
    result = validator.validate_block(temp_block)
    assert result.publisher_tier == "community"


def test_failing_validation_for_missing_trust_tier(
    test_publisher: PublisherRegistry,
    temp_block: Path,
    private_key: Ed25519PrivateKey,
):
    _write_manifest(temp_block, remove=("trust_tier",))
    BlockSigner.sign_block(
        block_path=temp_block,
        publisher_id="test_corp",
        private_key=private_key,
    )

    validator = BlockValidator(
        publisher_registry=test_publisher,
        certification_store_path=temp_block.parent / "certifications.json",
    )
    result = validator.validate_block(temp_block)

    assert result.status == "failed"
    assert any(
        "missing required manifest field: trust_tier" in reason
        for reason in result.reasons
    )


def test_failing_validation_for_invalid_trust_tier(
    test_publisher: PublisherRegistry,
    temp_block: Path,
    private_key: Ed25519PrivateKey,
):
    _write_manifest(temp_block, extra={"trust_tier": "contributor_unverified"})
    BlockSigner.sign_block(
        block_path=temp_block,
        publisher_id="test_corp",
        private_key=private_key,
    )

    validator = BlockValidator(
        publisher_registry=test_publisher,
        certification_store_path=temp_block.parent / "certifications.json",
    )
    result = validator.validate_block(temp_block)

    assert result.status == "failed"
    assert any("invalid trust_tier" in reason for reason in result.reasons)
    assert result.publisher_tier == "reviewed"


def test_failing_validation_for_missing_permissions(
    test_publisher: PublisherRegistry,
    temp_block: Path,
    private_key: Ed25519PrivateKey,
):
    _write_manifest(temp_block, remove=("permissions",))
    BlockSigner.sign_block(
        block_path=temp_block,
        publisher_id="test_corp",
        private_key=private_key,
    )

    validator = BlockValidator(
        publisher_registry=test_publisher,
        certification_store_path=temp_block.parent / "certifications.json",
    )
    result = validator.validate_block(temp_block)

    assert result.status == "failed"
    assert any(
        "missing required manifest field: permissions" in reason
        for reason in result.reasons
    )


def test_failing_validation_for_forbidden_import(
    test_publisher: PublisherRegistry,
    temp_block: Path,
    private_key: Ed25519PrivateKey,
):
    (temp_block / "block.py").write_text(
        "import os\n\ndef run(inputs):\n    return {'result': 'ok'}\n",
        encoding="utf-8",
    )
    BlockSigner.sign_block(
        block_path=temp_block,
        publisher_id="test_corp",
        private_key=private_key,
    )

    validator = BlockValidator(
        publisher_registry=test_publisher,
        certification_store_path=temp_block.parent / "certifications.json",
    )
    result = validator.validate_block(temp_block)

    assert result.status == "failed"
    assert any(
        "forbidden import 'os'" in reason for reason in result.reasons
    )


def test_failing_validation_for_forbidden_builtin(
    test_publisher: PublisherRegistry,
    temp_block: Path,
    private_key: Ed25519PrivateKey,
):
    (temp_block / "block.py").write_text(
        "def run(inputs):\n    return eval(inputs)\n",
        encoding="utf-8",
    )
    BlockSigner.sign_block(
        block_path=temp_block,
        publisher_id="test_corp",
        private_key=private_key,
    )

    validator = BlockValidator(
        publisher_registry=test_publisher,
        certification_store_path=temp_block.parent / "certifications.json",
    )
    result = validator.validate_block(temp_block)

    assert result.status == "failed"
    assert any(
        "forbidden builtin call 'eval'" in reason for reason in result.reasons
    )


def test_failing_validation_for_tampered_file(
    test_publisher: PublisherRegistry,
    temp_block: Path,
    private_key: Ed25519PrivateKey,
):
    BlockSigner.sign_block(
        block_path=temp_block,
        publisher_id="test_corp",
        private_key=private_key,
    )
    (temp_block / "block.py").write_text(
        "# tampered\n\ndef run(inputs):\n    return {'result': 'bad'}\n",
        encoding="utf-8",
    )

    validator = BlockValidator(
        publisher_registry=test_publisher,
        certification_store_path=temp_block.parent / "certifications.json",
    )
    result = validator.validate_block(temp_block)

    assert result.status == "failed"
    assert any(
        "digest mismatch" in reason for reason in result.reasons
    )


def test_certification_store_save_and_load(tmp_path: Path):
    path = tmp_path / "certifications.json"
    store = CertificationStore(path=path)

    result = BlockValidationResult(
        block_id="store_test",
        version="1.0.0",
        publisher_id="pub",
        status="passed",
        reasons=[],
    )
    store.save_result(result)

    store2 = CertificationStore(path=path)
    loaded = store2.get("store_test")
    assert loaded is not None
    assert loaded.status == "passed"
    assert loaded.block_id == "store_test"
    assert store2.is_certified("store_test") is True
