"""Honest-stub behavior tests for the Primavera Cloud connector block."""

import pytest

from app.blocks.primavera_cloud_connector import PrimaveraCloudConnectorBlock


def _configured_block():
    return PrimaveraCloudConnectorBlock(config={
        "primavera_base_url": "https://primavera.example.com",
        "primavera_client_id": "cid",
        "primavera_client_secret": "csecret",
        "primavera_username": "user",
        "primavera_password": "pass",
    })


@pytest.mark.asyncio
async def test_status_declares_honest_stub_provenance():
    block = PrimaveraCloudConnectorBlock()
    env = await block.execute({"action": "status"})
    assert env["status"] == "ok"
    body = env["result"]
    assert body["provenance"] == "honest-stub"
    assert "no donor" in body["donor"]
    assert body["implemented"] is False
    assert body["configured"] is False
    assert body["missing"] == [
        "primavera_base_url",
        "primavera_client_id",
        "primavera_client_secret",
        "primavera_username",
        "primavera_password",
    ]


@pytest.mark.asyncio
async def test_oauth_token_unconfigured_refused():
    env = await PrimaveraCloudConnectorBlock().execute({"action": "oauth_token"})
    assert env["status"] == "refused"
    assert "not configured" in env["error"]
    assert "primavera_client_id" in env["detail"]["missing"]


@pytest.mark.asyncio
async def test_etl_unconfigured_refused():
    env = await PrimaveraCloudConnectorBlock().execute({"action": "etl", "resource": "projects"})
    assert env["status"] == "refused"
    assert "not configured" in env["error"]


@pytest.mark.asyncio
async def test_oauth_token_configured_still_refused_no_donor():
    env = await _configured_block().execute({"action": "oauth_token"})
    assert env["status"] == "refused"
    assert "no donor adapter exists" in env["error"]
    assert env["detail"]["implemented"] is False


@pytest.mark.asyncio
async def test_etl_configured_still_refused_no_donor():
    env = await _configured_block().execute({"action": "etl", "resource": "activities"})
    assert env["status"] == "refused"
    assert "no donor adapter exists" in env["error"]


@pytest.mark.asyncio
async def test_capabilities_implemented_is_empty():
    env = await PrimaveraCloudConnectorBlock().execute({"action": "capabilities"})
    assert env["status"] == "ok"
    assert env["result"]["implemented"] == []


@pytest.mark.asyncio
async def test_unknown_action_error():
    env = await PrimaveraCloudConnectorBlock().execute({"action": "delete_project"})
    assert env["status"] == "error"
    assert "unknown action" in env["error"]
