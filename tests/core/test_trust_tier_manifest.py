"""trust_tier on block.json is required and value-checked.

Distinct from publisher_tier (certified/reviewed/community/revoked). The
accepted set is pinned to Factory ACCEPTED_TRUST_TIERS at eacc254.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core.block_validation import BlockValidator
from app.core.publisher_registry import BlockSigner, PublisherRegistry
from app.core.trust_tier import ACCEPTED_TRUST_TIERS, check_trust_tier

ROOT = Path(__file__).resolve().parents[2]
_AUDIT = ROOT / "scripts" / "audit_block_standards.py"
_spec = importlib.util.spec_from_file_location("audit_block_standards", _AUDIT)
_audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_audit)
REQUIRED_MANIFEST_KEYS = _audit.REQUIRED_MANIFEST_KEYS
audit_block = _audit.audit_block

REGISTRY = ROOT / "block_registry"


def test_accepted_trust_tiers_pin_factory_eacc254():
    """Literal pin to <private-repo> compliance_gate.ACCEPTED_TRUST_TIERS."""
    assert ACCEPTED_TRUST_TIERS == frozenset({"platform", "contributor_reviewed"})


def test_trust_tier_is_not_publisher_tier():
    publisher_tiers = frozenset({"certified", "reviewed", "community", "revoked"})
    assert ACCEPTED_TRUST_TIERS.isdisjoint(publisher_tiers)


def test_required_manifest_keys_include_trust_tier():
    assert "trust_tier" in REQUIRED_MANIFEST_KEYS
    assert "publisher_tier" not in REQUIRED_MANIFEST_KEYS


def test_check_trust_tier_fails_closed_when_missing():
    assert check_trust_tier({}) == ["missing required manifest field: trust_tier"]
    assert check_trust_tier({"trust_tier": ""}) == [
        "missing required manifest field: trust_tier"
    ]
    assert check_trust_tier({"trust_tier": None}) == [
        "missing required manifest field: trust_tier"
    ]


def test_check_trust_tier_rejects_unknown_and_kit_unverified():
    reasons = check_trust_tier({"trust_tier": "contributor_unverified"})
    assert reasons
    assert "invalid trust_tier" in reasons[0]
    assert check_trust_tier({"trust_tier": "certified"})  # publisher_tier value


@pytest.mark.parametrize("tier", sorted(ACCEPTED_TRUST_TIERS))
def test_check_trust_tier_accepts_factory_values(tier: str):
    assert check_trust_tier({"trust_tier": tier}) == []


def test_audit_fails_closed_when_trust_tier_missing(tmp_path: Path):
    block_dir = tmp_path / "formula_executor"
    block_dir.mkdir()
    (block_dir / "block.json").write_text(
        json.dumps(
            {
                "id": "formula_executor",
                "name": "Formula Executor",
                "version": "1.0.0",
                "description": "test",
                "inputs": [{"name": "input"}],
                "outputs": [{"name": "result"}],
                "execution": {"type": "docker", "image": "x"},
                "ui_schema": [],
                "tags": [],
                "layer": 3,
                "requires": [],
            }
        ),
        encoding="utf-8",
    )
    (block_dir / "block.py").write_text("def run():\n    return {}\n", encoding="utf-8")
    (block_dir / "Dockerfile").write_text("FROM python:3.11\n", encoding="utf-8")

    result = audit_block(block_dir)
    assert any("trust_tier" in err for err in result["errors"])


def test_audit_rejects_invalid_trust_tier(tmp_path: Path):
    block_dir = tmp_path / "formula_executor"
    block_dir.mkdir()
    (block_dir / "block.json").write_text(
        json.dumps(
            {
                "id": "formula_executor",
                "name": "Formula Executor",
                "version": "1.0.0",
                "description": "test",
                "inputs": [{"name": "input"}],
                "outputs": [{"name": "result"}],
                "execution": {"type": "docker", "image": "x"},
                "ui_schema": [],
                "tags": [],
                "layer": 3,
                "requires": [],
                "trust_tier": "community",
            }
        ),
        encoding="utf-8",
    )
    (block_dir / "block.py").write_text("def run():\n    return {}\n", encoding="utf-8")
    (block_dir / "Dockerfile").write_text("FROM python:3.11\n", encoding="utf-8")

    result = audit_block(block_dir)
    assert any("invalid trust_tier" in err for err in result["errors"])


def test_audit_accepts_platform_trust_tier(tmp_path: Path):
    block_dir = tmp_path / "formula_executor"
    block_dir.mkdir()
    (block_dir / "block.json").write_text(
        json.dumps(
            {
                "id": "formula_executor",
                "name": "Formula Executor",
                "version": "1.0.0",
                "description": "test",
                "inputs": [{"name": "input"}],
                "outputs": [{"name": "result"}],
                "execution": {"type": "docker", "image": "x"},
                "ui_schema": [],
                "tags": [],
                "layer": 3,
                "requires": [],
                "trust_tier": "platform",
            }
        ),
        encoding="utf-8",
    )
    (block_dir / "block.py").write_text("def run():\n    return {}\n", encoding="utf-8")
    (block_dir / "Dockerfile").write_text("FROM python:3.11\n", encoding="utf-8")

    result = audit_block(block_dir)
    assert not any("trust_tier" in err for err in result["errors"])


def test_every_registry_manifest_declares_an_accepted_trust_tier():
    missing, invalid = [], []
    for block_dir in sorted(p for p in REGISTRY.iterdir() if p.is_dir()):
        manifest_path = block_dir / "block.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        reasons = check_trust_tier(manifest)
        if any("missing" in r for r in reasons):
            missing.append(block_dir.name)
        elif reasons:
            invalid.append((block_dir.name, reasons))
    assert not missing, f"block.json missing trust_tier: {missing}"
    assert not invalid, f"block.json invalid trust_tier: {invalid}"


def test_formula_executor_declares_platform_trust_tier():
    manifest = json.loads(
        (REGISTRY / "formula_executor" / "block.json").read_text(encoding="utf-8")
    )
    assert manifest["trust_tier"] == "platform"
    assert "publisher_tier" not in manifest


def test_validation_fails_closed_without_trust_tier(tmp_path: Path):
    private_key = Ed25519PrivateKey.generate()
    raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    import base64

    public_key_b64 = base64.b64encode(raw).decode("ascii")
    registry = PublisherRegistry(path=tmp_path / "publishers.json")
    registry.register(
        publisher_id="test_corp",
        name="Test Corp",
        contact="security@testcorp.example",
        public_key=public_key_b64,
        tier="reviewed",
    )

    block_path = tmp_path / "test_block"
    block_path.mkdir()
    (block_path / "block.json").write_text(
        json.dumps(
            {
                "id": "test_block",
                "name": "Test Block",
                "version": "1.0.0",
                "publisher_id": "test_corp",
                "permissions": {
                    "network": False,
                    "filesystem": False,
                    "imports": [],
                    "blocks": [],
                },
            }
        ),
        encoding="utf-8",
    )
    (block_path / "block.py").write_text(
        "def run(inputs):\n    return {'result': 'ok'}\n", encoding="utf-8"
    )
    BlockSigner.sign_block(
        block_path=block_path,
        publisher_id="test_corp",
        private_key=private_key,
    )

    validator = BlockValidator(
        publisher_registry=registry,
        certification_store_path=tmp_path / "certs.json",
    )
    result = validator.validate_block(block_path)
    assert result.status == "failed"
    assert any("trust_tier" in reason for reason in result.reasons)
    assert result.publisher_tier == "reviewed"


def test_validation_passes_with_accepted_trust_tier(tmp_path: Path):
    private_key = Ed25519PrivateKey.generate()
    raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    import base64

    public_key_b64 = base64.b64encode(raw).decode("ascii")
    registry = PublisherRegistry(path=tmp_path / "publishers.json")
    registry.register(
        publisher_id="test_corp",
        name="Test Corp",
        contact="security@testcorp.example",
        public_key=public_key_b64,
        tier="reviewed",
    )

    block_path = tmp_path / "test_block"
    block_path.mkdir()
    (block_path / "block.json").write_text(
        json.dumps(
            {
                "id": "test_block",
                "name": "Test Block",
                "version": "1.0.0",
                "publisher_id": "test_corp",
                "permissions": {
                    "network": False,
                    "filesystem": False,
                    "imports": [],
                    "blocks": [],
                },
                "trust_tier": "platform",
            }
        ),
        encoding="utf-8",
    )
    (block_path / "block.py").write_text(
        "def run(inputs):\n    return {'result': 'ok'}\n", encoding="utf-8"
    )
    BlockSigner.sign_block(
        block_path=block_path,
        publisher_id="test_corp",
        private_key=private_key,
    )

    validator = BlockValidator(
        publisher_registry=registry,
        certification_store_path=tmp_path / "certs.json",
    )
    result = validator.validate_block(block_path)
    assert result.status == "passed"
    assert result.reasons == []
    assert result.publisher_tier == "reviewed"
