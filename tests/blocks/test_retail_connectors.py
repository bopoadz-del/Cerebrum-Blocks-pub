"""Retail connectors â€” ported <private-product> connector contract.

Asserts the honest-stub discipline: mock-functional connectors produce
deterministic fictional data with no credentials; honest-stub connectors
raise ConnectorError (surfaced as refused) rather than fabricate vendor
data; read-only connectors refuse push.
"""
from __future__ import annotations

import asyncio

import pytest

from app.blocks.retail_connectors import (
    ALL_STATUSES,
    ConnectorError,
    ConnectorStatus,
    RetailConnectorsBlock,
)


def _run(coro):
    return asyncio.run(coro)


def _p(b, payload):
    return _run(b.process(payload))


def test_list_shows_all_eight_connectors_with_honest_statuses():
    b = RetailConnectorsBlock()
    r = _p(b, {"action": "list"})
    assert r["status"] == "ok"
    cards = {c["connector_id"]: c for c in r["result"]["connectors"]}
    assert set(cards) == {
        "pos", "inventory_wms", "crm_loyalty", "supplier_edi",
        "entra_id", "power_bi", "sap_erp", "store_digital_twin",
    }
    for c in cards.values():
        assert c["status"] in ALL_STATUSES
    # Unconfigured: mock-functional connectors report mock, stubs report disabled.
    assert cards["pos"]["mock_functional"] is True
    assert cards["sap_erp"]["mock_functional"] is False
    assert cards["sap_erp"]["status"] == ConnectorStatus.DISABLED
    assert cards["pos"]["status"] == ConnectorStatus.MOCK


def test_pos_pull_is_deterministic_mock_with_no_credentials():
    b = RetailConnectorsBlock()
    r1 = _p(b, {"action": "pull", "connector_id": "pos"})
    r2 = _p(b, {"action": "pull", "connector_id": "pos"})
    assert r1["status"] == "ok" and r2["status"] == "ok"
    assert r1["result"]["pull"]["source"] == "mock"
    assert r1["result"]["pull"] == r2["result"]["pull"]  # deterministic
    assert len(r1["result"]["pull"]["records"]) == 12


def test_sap_erp_pull_refuses_without_fabricating():
    b = RetailConnectorsBlock()
    r = _p(b, {"action": "pull", "connector_id": "sap_erp"})
    assert r["status"] == "refused"
    assert "not implemented" in r["error"]
    assert r["detail"]["error_code"] is not None


def test_store_digital_twin_pull_never_fabricates_planograms():
    b = RetailConnectorsBlock()
    r = _p(b, {"action": "pull", "connector_id": "store_digital_twin"})
    assert r["status"] == "refused"
    assert "not implemented" in r["error"]


def test_push_on_read_only_connector_refuses():
    b = RetailConnectorsBlock()
    r = _p(b, {"action": "push", "connector_id": "pos", "operation": "write_txn", "payload": {}})
    assert r["status"] == "refused"
    assert "read-only" in r["error"]
    assert r["detail"]["error_code"] == "read_only"


def test_normalize_requires_records_list():
    b = RetailConnectorsBlock()
    r = _p(b, {"action": "normalize", "connector_id": "pos", "records": "not-a-list"})
    assert r["status"] == "error"
    assert "records" in r["error"]


def test_normalize_pos_computes_amount():
    b = RetailConnectorsBlock()
    r = _p(b, {"action": "normalize", "connector_id": "pos", "records": [
        {"txn_id": "T1", "store_id": "S1", "till_id": "T1", "ts": "2026-01-01",
         "sku": "X", "qty": 2, "unit_price": 1.5, "discount": 0.0,
         "payment_type": "card", "type": "sale"},
    ]})
    assert r["status"] == "ok"
    assert r["result"]["normalized"][0]["amount"] == pytest.approx(3.0)
    assert r["result"]["normalized"][0]["record_type"] == "sale"


def test_unknown_connector_and_action_are_errors():
    b = RetailConnectorsBlock()
    assert _p(b, {"action": "pull", "connector_id": "nope"})["status"] == "error"
    assert _p(b, {"action": "bogus", "connector_id": "pos"})["status"] == "error"


def test_connector_error_carries_error_code():
    err = ConnectorError("no", error_code="not_configured")
    assert err.error_code == "not_configured"
    assert ConnectorStatus.DEGRADED in ALL_STATUSES
