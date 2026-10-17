"""Restricted blocks are gated at RESOLUTION, closing dispatch-path bypasses.

The audit found ``enforce_block_access`` was only called by ``/v1/execute`` and
``/chain``. ``/swarm/execute``, ``/workflow/run``, ``/notify``, and other paths
reached blocks by name via ``get_block_instance`` / ``_create_block_instance``
with no tier check, so a standard-tier key could reach the ``database`` (raw
SQL), ``code``/``sandbox`` (RCE), and ``secrets`` (vault) primitives.

These tests pin the choke point: with a standard-tier request in context, a
restricted block cannot be resolved; with unlimited tier, or no request context
(boot/system), it can.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core import security
from app import dependencies


@pytest.fixture(autouse=True)
def _reset_auth():
    security.set_current_auth(None)
    security._in_request.set(False)
    yield
    security.set_current_auth(None)
    security._in_request.set(False)


RESTRICTED = ["database", "code", "sandbox", "secrets"]


def _in_flight(auth):
    """Simulate an in-flight request with the given auth (as the middleware does)."""
    security._in_request.set(True)
    security.set_current_auth(auth)


@pytest.mark.parametrize("block", RESTRICTED)
def test_standard_tier_cannot_resolve_restricted_block(block):
    _in_flight({"tier": "standard", "user": "attacker"})
    with pytest.raises(HTTPException) as exc:
        dependencies.get_block_instance(block)
    assert exc.value.status_code == 403


@pytest.mark.parametrize("block", RESTRICTED)
def test_create_block_instance_is_also_gated(block):
    # Direct _create_block_instance (the notification/async_processor bypass)
    # must be gated too, not just get_block_instance.
    from app.dependencies import BLOCK_REGISTRY

    if block not in BLOCK_REGISTRY:
        pytest.skip(f"{block} not registered in this environment")
    _in_flight({"tier": "standard", "user": "attacker"})
    with pytest.raises(HTTPException) as exc:
        dependencies._create_block_instance(BLOCK_REGISTRY[block])
    assert exc.value.status_code == 403


@pytest.mark.parametrize("block", RESTRICTED)
def test_in_flight_request_with_unknown_tier_is_denied(block):
    # FAIL CLOSED: a request is in flight but no tier was ever set (an
    # unauthenticated or mis-wired route that skipped require_api_key). The gate
    # must DENY, not wave it through.
    security._in_request.set(True)
    security.set_current_auth(None)  # tier unknown
    with pytest.raises(HTTPException) as exc:
        dependencies.get_block_instance(block)
    assert exc.value.status_code == 403


def test_unlimited_tier_is_allowed_past_the_gate():
    # Unlimited tier passes the gate (it may still fail later on missing config,
    # but it must NOT be a 403 from the resolution gate).
    _in_flight({"tier": "unlimited", "user": "admin"})
    try:
        dependencies.get_block_instance("database")
    except HTTPException as exc:
        assert exc.value.status_code != 403, "unlimited tier wrongly blocked at resolution"
    except Exception:
        pass  # non-HTTP failures (missing DB config) are fine — the gate let it through


def test_no_request_context_is_permissive():
    # Boot / registry validation / system warm-up resolve with NO request in
    # flight and must not be blocked (the only permissive case).
    security.set_current_auth(None)
    security._in_request.set(False)
    try:
        dependencies.get_block_instance("database")
    except HTTPException as exc:
        assert exc.value.status_code != 403, "system resolution wrongly blocked"
    except Exception:
        pass


def test_unrestricted_block_is_never_gated():
    _in_flight({"tier": "standard", "user": "normal"})
    # memory is not a restricted primitive — standard tier resolves it fine.
    inst = dependencies.get_block_instance("memory")
    assert inst is not None
