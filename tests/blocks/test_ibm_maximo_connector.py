"""Real-behavior tests for the IBM Maximo connector block (hotelops port)."""

import pytest

from app.blocks.ibm_maximo_connector import IbmMaximoConnectorBlock


def _live_block():
    return IbmMaximoConnectorBlock(config={
        "maximo_base_url": "https://maximo.example.com",
        "maximo_api_key": "test-apikey",
    })


ASSET_ROW = {
    "asset_id": "A-100",
    "asset_type": "AHU",
    "serial_number": "SN-1",
    "location": "R1",
    "evidence_class": "asset_record",
    "statutory_flag": True,
}


@pytest.mark.asyncio
async def test_status_reports_live_configuration():
    assert (await IbmMaximoConnectorBlock().execute({"action": "status"}))["result"]["live_configured"] is False
    assert (await _live_block().execute({"action": "status"}))["result"]["live_configured"] is True


@pytest.mark.asyncio
async def test_fetch_unconfigured_refused_no_fixtures():
    env = await IbmMaximoConnectorBlock().execute({"action": "fetch", "resource": "assets"})
    assert env["status"] == "refused"
    assert "no maximo fixture pack" in env["error"]


@pytest.mark.asyncio
async def test_fetch_unknown_resource_refused():
    env = await _live_block().execute({"action": "fetch", "resource": "invoices"})
    assert env["status"] == "refused"
    assert "out of scope" in env["error"]


@pytest.mark.asyncio
async def test_normalise_assets_maps_donor_event_shape():
    env = await IbmMaximoConnectorBlock().execute({
        "action": "normalise",
        "resource": "assets",
        "raw": {"records": [ASSET_ROW]},
    })
    assert env["status"] == "ok"
    events = env["result"]["events"]
    assert len(events) == 1
    ev = events[0]
    assert ev["topic"] == "ops.engineering.asset"
    assert ev["surface"] == "ops"
    assert ev["source"] == "maximo_cmms"
    assert ev["payload"]["asset_id"] == "A-100"
    assert ev["payload"]["statutory_flag"] is True
    assert ev["payload"]["source_system"] == "maximo"


@pytest.mark.asyncio
async def test_normalise_workorders_maps_donor_event_shape():
    env = await IbmMaximoConnectorBlock().execute({
        "action": "normalise",
        "resource": "workorders",
        "raw": {"records": [{"wo": "WO-7", "asset_id": "A-100", "status": "WAPPR"}]},
    })
    assert env["status"] == "ok"
    ev = env["result"]["events"][0]
    assert ev["topic"] == "ops.cmms.workorder"
    assert ev["payload"] == {"wo": "WO-7", "asset_id": "A-100", "status": "WAPPR"}


@pytest.mark.asyncio
async def test_normalise_procore_asset_refused_out_of_scope():
    row = {**ASSET_ROW, "source_system": "procore"}
    env = await IbmMaximoConnectorBlock().execute({
        "action": "normalise", "resource": "assets", "raw": {"records": [row]},
    })
    assert env["status"] == "refused"
    assert "A-100" in env["error"] and "procore" in env["error"]
    assert "out of scope" in env["error"]


@pytest.mark.asyncio
async def test_normalise_forbidden_claimed_source_refused():
    env = await IbmMaximoConnectorBlock().execute({
        "action": "normalise",
        "resource": "assets",
        "source_system": "bim",
        "raw": {"records": [ASSET_ROW]},
    })
    assert env["status"] == "refused"
    assert env["detail"]["code"] == "construction_pm_out_of_scope"


@pytest.mark.asyncio
async def test_normalise_without_raw_refused():
    env = await IbmMaximoConnectorBlock().execute({"action": "normalise", "resource": "assets"})
    assert env["status"] == "refused"
    assert "requires 'raw'" in env["error"]


@pytest.mark.asyncio
async def test_ingest_with_raw_is_deterministic():
    env = await IbmMaximoConnectorBlock().execute({
        "action": "ingest", "resource": "assets", "raw": {"records": [ASSET_ROW]},
    })
    assert env["status"] == "ok"
    assert env["result"]["mode"] == "raw"
    assert env["result"]["emitted"] == 1
    assert env["result"]["events"][0]["topic"] == "ops.engineering.asset"


@pytest.mark.asyncio
async def test_ingest_unconfigured_without_raw_refused():
    env = await IbmMaximoConnectorBlock().execute({"action": "ingest", "resource": "assets"})
    assert env["status"] == "refused"


@pytest.mark.asyncio
async def test_fetch_live_uses_donor_url_and_apikey_header(monkeypatch):
    captured = {}

    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"records": [ASSET_ROW]}

    def fake_get(url, headers=None, params=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["params"] = params
        captured["timeout"] = timeout
        return FakeResp()

    monkeypatch.setattr("httpx.get", fake_get)
    env = await _live_block().execute({
        "action": "fetch", "resource": "assets", "params": {"lean": "1"},
    })
    assert env["status"] == "ok"
    assert captured["url"] == "https://maximo.example.com/os/assets"
    assert captured["headers"] == {"apikey": "test-apikey"}
    assert captured["params"] == {"lean": "1"}
    assert captured["timeout"] == 20


@pytest.mark.asyncio
async def test_fetch_live_http_error_is_error_envelope(monkeypatch):
    class BoomResp:
        def raise_for_status(self):
            raise RuntimeError("401 Unauthorized")

    monkeypatch.setattr("httpx.get", lambda *a, **k: BoomResp())
    env = await _live_block().execute({"action": "fetch", "resource": "assets"})
    assert env["status"] == "error"
    assert "401" in env["error"]


@pytest.mark.asyncio
async def test_unknown_action_error():
    env = await IbmMaximoConnectorBlock().execute({"action": "delete_asset"})
    assert env["status"] == "error"
    assert "unknown action" in env["error"]
