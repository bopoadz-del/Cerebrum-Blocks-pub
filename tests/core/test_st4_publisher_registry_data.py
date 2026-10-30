"""ST-4: the shipped publisher registry (data/publishers.json) is pinned.

Every test here reads the real shipped data or the real enforcement code;
no private key is created or touched except the synthetic per-test keys
used to sign throwaway temp blocks.
"""

import base64
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import app.blocks as blocks_pkg
from app.core.block_capabilities import BlockCapabilities
from app.core.publisher_registry import (
    BlockSigner,
    BlockVerifier,
    PublisherRecord,
    PublisherRegistry,
)

ROOT = Path(__file__).resolve().parents[2]
PUBLISHERS_JSON = ROOT / "data" / "publishers.json"
PUB_FILE = ROOT / "data" / "publishers" / "cerebrum_platform.pub"
# SHA-256 of the raw 32-byte Ed25519 public key restored from origin 7ba787b2.
PINNED_PLATFORM_KEY_SHA256 = "3c0051874b4349545b037fab63772ab2533e4ef9a3b37d0d2ad4f93a51c11703"
# A block signed by the owner in-repo; verifies with the restored key.
KNOWN_SIGNED_BLOCK = ROOT / "block_registry" / "adaptive_router"


def _shipped():
    return {p["publisher_id"]: p for p in json.loads(PUBLISHERS_JSON.read_text())["publishers"]}


# ---- 1. tiers are told apart -------------------------------------------------

def test_shipped_platform_publisher_is_certified_exactly():
    rec = _shipped()["cerebrum_platform"]
    assert rec["tier"] == "certified", rec["tier"]
    assert PublisherRegistry(PUBLISHERS_JSON).get("cerebrum_platform").effective_tier == "certified"


@pytest.mark.parametrize(
    "tier,elevated,out_of_process",
    [
        ("certified", True, False),   # certified: in-process even with network
        ("reviewed", True, True),     # reviewed + elevated caps: sandboxed
        ("reviewed", False, False),   # reviewed + safe caps: in-process
        ("community", False, True),
        ("revoked", False, True),
    ],
)
def test_tiers_route_differently(tier, elevated, out_of_process):
    caps = BlockCapabilities(network=elevated, publisher_tier=tier)
    assert caps.must_run_out_of_process is out_of_process, (tier, elevated)


def test_certified_and_reviewed_differ_for_the_same_elevated_block():
    c = BlockCapabilities(network=True, publisher_tier="certified").must_run_out_of_process
    r = BlockCapabilities(network=True, publisher_tier="reviewed").must_run_out_of_process
    assert c != r, (c, r)


def test_resolved_tier_for_a_real_platform_block_is_certified():
    validator = type("V", (), {"publisher_registry": PublisherRegistry(PUBLISHERS_JSON),
                               "certification_store": None})()
    assert blocks_pkg._resolve_publisher_tier("adaptive_router", validator) == "certified"


# ---- 2. revoked_at is honoured -----------------------------------------------

def _signed_block(tmp_path, revoked_at):
    key = Ed25519PrivateKey.generate()  # synthetic, per-test, never persisted
    pub = base64.b64encode(key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    reg = PublisherRegistry(tmp_path / "publishers.json")
    reg.register("p1", "P1", "p1@example.invalid", pub, tier="certified")
    if revoked_at is not None:
        reg.get("p1").revoked_at = revoked_at  # stamp without tier change
    block = tmp_path / "b"
    block.mkdir()
    (block / "block.json").write_text(json.dumps({"name": "b", "version": "1.0.0"}))
    (block / "block.py").write_text("def run(i):\n    return i\n")
    BlockSigner.sign_block(block, "p1", key)  # in-memory only
    return reg, block


def test_a_publisher_with_revoked_at_is_refused(tmp_path):
    reg, block = _signed_block(tmp_path, "2026-10-01T00:00:00+00:00")
    assert reg.is_trusted("p1") is False
    assert reg.get("p1").effective_tier == "revoked"
    res = BlockVerifier(reg).verify_block(block)
    assert res["verified"] is False and "revoked" in res["reason"], res


def test_a_publisher_without_revoked_at_is_accepted(tmp_path):
    reg, block = _signed_block(tmp_path, None)
    assert reg.is_trusted("p1") is True
    assert reg.get("p1").effective_tier == "certified"
    res = BlockVerifier(reg).verify_block(block)
    assert res["verified"] is True, res


def test_revoke_sets_the_stamp_and_refuses(tmp_path):
    reg, _ = _signed_block(tmp_path, None)
    reg.revoke("p1")
    rec = PublisherRegistry(tmp_path / "publishers.json").get("p1")
    assert rec.revoked_at is not None and rec.is_revoked is True


def test_record_level_revoked_at_drives_is_revoked():
    base = dict(publisher_id="x", name="x", contact="x", public_key="k", tier="certified")
    assert PublisherRecord(**base).is_revoked is False
    assert PublisherRecord(**base, revoked_at="2026-01-01T00:00:00Z").is_revoked is True


def test_shipped_platform_publisher_is_not_revoked():
    assert _shipped()["cerebrum_platform"]["revoked_at"] is None
    assert PublisherRegistry(PUBLISHERS_JSON).is_trusted("cerebrum_platform") is True


# ---- 3. the shipped key is pinned and verifies real signed data -------------

def test_platform_key_matches_pinned_fingerprint():
    raw = base64.b64decode(_shipped()["cerebrum_platform"]["public_key"])
    assert hashlib.sha256(raw).hexdigest() == PINNED_PLATFORM_KEY_SHA256


def test_platform_key_verifies_a_known_owner_signed_block():
    res = BlockVerifier(PublisherRegistry(PUBLISHERS_JSON)).verify_block(KNOWN_SIGNED_BLOCK)
    assert res["verified"] is True, res
    assert res["publisher_id"] == "cerebrum_platform"


# ---- 4. the .pub file is the same key ---------------------------------------

def test_pub_file_matches_publishers_json():
    assert PUB_FILE.read_text(encoding="utf-8").strip() == _shipped()["cerebrum_platform"]["public_key"]


def test_resolved_tier_honours_a_revoked_at_stamp(tmp_path):
    data = json.loads(PUBLISHERS_JSON.read_text())
    data["publishers"][0]["revoked_at"] = "2026-10-01T00:00:00+00:00"
    path = tmp_path / "publishers.json"
    path.write_text(json.dumps(data))
    validator = type("V", (), {"publisher_registry": PublisherRegistry(path),
                               "certification_store": None})()
    assert blocks_pkg._resolve_publisher_tier("adaptive_router", validator) == "revoked"


_BASE = dict(publisher_id="x", name="x", contact="x", public_key="k")


@pytest.mark.parametrize(
    "case,tier,revoked_at,revoked",
    [
        ("R1 certified, no stamp", "certified", None, False),
        ("R2 tier revoked, no stamp", "revoked", None, True),
        ("R3 reviewed, no stamp", "reviewed", None, False),
        ("R4 community, no stamp", "community", None, False),
        ("R5 certified, past stamp", "certified", "2026-01-01T00:00:00+00:00", True),
        ("R9 certified, empty-string stamp", "certified", "", True),
        ("R10 certified, future stamp", "certified", "2999-01-01T00:00:00+00:00", True),
    ],
)
def test_publisher_record_revocation_matrix(case, tier, revoked_at, revoked, tmp_path):
    rec = PublisherRecord(**_BASE, tier=tier, revoked_at=revoked_at)
    assert rec.is_revoked is revoked, case
    assert (rec.effective_tier == "revoked") is revoked, case
    if not revoked:
        assert rec.effective_tier == tier, case
    path = tmp_path / "publishers.json"
    path.write_text(json.dumps({"version": 1, "publishers": [rec.to_dict()]}))
    assert PublisherRegistry(path).is_trusted("x") is (not revoked), case
