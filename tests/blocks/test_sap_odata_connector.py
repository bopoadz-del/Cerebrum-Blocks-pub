"""Honest-stub behavior tests for the SAP OData connector block."""

import pytest

from app.blocks.sap_odata_connector import SapOdataConnectorBlock


def _configured_block():
    return SapOdataConnectorBlock(config={
        "sap_odata_base_url": "https://sap.example.com",
        "sap_odata_username": "svc-user",
        "sap_odata_password": "svc-pass",
    })


@pytest.mark.asyncio
async def test_status_declares_honest_stub_provenance():
    block = SapOdataConnectorBlock()
    env = await block.execute({"action": "status"})
    assert env["status"] == "ok"
    body = env["result"]
    assert body["provenance"] == "honest-stub"
    assert "no donor" in body["donor"]
    assert body["implemented"] is False
    assert body["configured"] is False
    assert set(body["missing"]) == {
        "sap_odata_base_url", "sap_odata_username", "sap_odata_password"}


@pytest.mark.asyncio
async def test_gl_accounts_unconfigured_refused():
    block = SapOdataConnectorBlock()
    env = await block.execute({"action": "list_gl_accounts"})
    assert env["status"] == "refused"
    assert "not configured" in env["error"]
    assert "sap_odata_base_url" in env["detail"]["missing"]


@pytest.mark.asyncio
async def test_po_headers_unconfigured_refused():
    block = SapOdataConnectorBlock()
    env = await block.execute({"action": "list_po_headers"})
    assert env["status"] == "refused"
    assert "not configured" in env["error"]


@pytest.mark.asyncio
async def test_gl_accounts_configured_still_refused_no_donor():
    block = _configured_block()
    env = await block.execute({"action": "list_gl_accounts"})
    assert env["status"] == "refused"
    assert "no donor adapter exists" in env["error"]
    assert env["detail"]["implemented"] is False


@pytest.mark.asyncio
async def test_po_headers_configured_still_refused_no_donor():
    block = _configured_block()
    env = await block.execute({"action": "list_po_headers"})
    assert env["status"] == "refused"
    assert "no donor adapter exists" in env["error"]


@pytest.mark.asyncio
async def test_capabilities_implemented_is_empty():
    block = SapOdataConnectorBlock()
    env = await block.execute({"action": "capabilities"})
    assert env["status"] == "ok"
    assert env["result"]["implemented"] == []


@pytest.mark.asyncio
async def test_unknown_action_error():
    block = SapOdataConnectorBlock()
    env = await block.execute({"action": "write_vendor"})
    assert env["status"] == "error"
    assert "unknown action" in env["error"]
