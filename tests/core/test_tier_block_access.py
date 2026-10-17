"""The tier block-access boundary must be enforced server-side on /v1/execute."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.routers.execute import ExecuteRequest, _run_block


class _EchoBlock:
    async def execute(self, input_data, params):
        return {
            "block": "x",
            "request_id": "t",
            "status": "success",
            "result": {"ok": True},
            "confidence": 1.0,
            "source_id": "x-t",
            "metadata": {},
            "processing_time_ms": 0,
        }


def _patches(names):
    echo = _EchoBlock()
    return [
        patch("app.routers.execute.BLOCK_REGISTRY", {n: object for n in names}),
        patch("app.routers.execute.get_block_instance", lambda n: echo),
        patch("app.routers.execute.adapt_input", lambda d, b: d),
    ]


async def _run(block, tier):
    auth = {"id": "k", "email": "t@example.com", "tier": tier}
    ps = _patches([block])
    for p in ps:
        p.start()
    try:
        return await _run_block(ExecuteRequest(block=block, input={"text": "hi"}, params={}), auth)
    finally:
        for p in ps:
            p.stop()


@pytest.mark.asyncio
async def test_free_tier_can_use_trial_blocks():
    response = await _run("knowledge", "free")
    assert response["result"]["ok"] is True


@pytest.mark.asyncio
async def test_free_tier_denied_outside_allowed_list():
    with pytest.raises(HTTPException) as exc:
        await _run("construction_v2", "free")
    assert exc.value.status_code == 403
    assert "tier" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_pro_tier_unrestricted():
    response = await _run("construction_v2", "pro")
    assert response["result"]["ok"] is True


# ── The tiers the live authenticator actually issues ──────────────────────
#
# The audit found this gate was a silent no-op: it built
# `Tier(str(raw_tier).lower())`, which raises ValueError for "standard" and
# "unlimited" — the only two tier strings `app/core/auth.py::_load_keys`
# ever stamps on a key — and the `except ValueError: return` branch waved
# every real request through. The tests above did not catch it because they
# only exercise "free"/"pro", the vocabulary the enum happens to accept.
#
# So: derive the tier strings from the issuer itself rather than restating
# them, and run the allow/deny matrix over what production emits.


def _tiers_issued_by_live_auth(monkeypatch) -> set:
    """Read the tier values straight out of the key loader."""
    from app.core.auth import APIKeyAuth

    monkeypatch.setenv("ENV", "test")  # loads cb_dev_key
    monkeypatch.setenv("CEREBRUM_MASTER_KEY", "test-master-key")
    monkeypatch.setenv("CEREBRUM_API_KEY_ACME", "test-tenant-key")

    # Bypass __init__: we want the key table, not a rate-limit database.
    loader = APIKeyAuth.__new__(APIKeyAuth)
    keys = APIKeyAuth._load_keys(loader)
    tiers = {str(data.get("tier")) for data in keys.values()}
    assert tiers, "expected the loader to issue at least one key"
    return tiers


def test_every_issued_tier_string_is_mapped(monkeypatch):
    """The regression guard. If a new tier string is introduced in
    `_load_keys` without a TIER_ALIASES entry, the allowlist silently stops
    applying to those keys — exactly the original defect. Fail here
    instead."""
    from app.core.api_keys import TIER_ALIASES, resolve_tier

    issued = _tiers_issued_by_live_auth(monkeypatch)
    # Pin the known set too, so deleting a key type is also visible.
    assert {"standard", "unlimited"} <= issued
    unmapped = {t for t in issued if resolve_tier(t) is None}
    assert not unmapped, (
        f"tier string(s) {sorted(unmapped)} are issued by app/core/auth.py but "
        f"absent from api_keys.TIER_ALIASES ({sorted(TIER_ALIASES)})"
    )


# (tier string, block, expected_allowed)
#
# "knowledge" is on the FREE allowlist; "construction_v2" is not.
_TIER_MATRIX = [
    # Live vocabulary: neither may be silently skipped.
    ("standard", "knowledge", True),
    ("standard", "construction_v2", True),
    ("unlimited", "knowledge", True),
    ("unlimited", "construction_v2", True),
    # Billing vocabulary.
    ("free", "knowledge", True),
    ("free", "construction_v2", False),
    ("pro", "construction_v2", True),
    ("enterprise", "construction_v2", True),
    # Case must not decide whether a security control runs.
    ("UNLIMITED", "construction_v2", True),
    ("Standard", "construction_v2", True),
    ("  free  ", "construction_v2", False),
    # An unrecognised tier must fail CLOSED, not fall through the gate.
    ("bogus_tier", "construction_v2", False),
    ("bogus_tier", "knowledge", True),
    ("", "construction_v2", False),
]


@pytest.mark.parametrize("tier,block,allowed", _TIER_MATRIX)
@pytest.mark.asyncio
async def test_tier_block_matrix(tier, block, allowed):
    if allowed:
        response = await _run(block, tier)
        assert response["result"]["ok"] is True
    else:
        with pytest.raises(HTTPException) as exc:
            await _run(block, tier)
        assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_primary_gate_still_denies_restricted_blocks_to_standard():
    """`enforce_block_access` is the primary control and keys off
    "unlimited" directly. The tier fix must not weaken it."""
    with pytest.raises(HTTPException) as exc:
        await _run("secrets", "standard")
    assert exc.value.status_code == 403
