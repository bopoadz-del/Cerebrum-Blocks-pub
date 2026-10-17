"""Mock-functional behavior tests for the Power BI connector block (<client> port)."""

import base64
import csv
import io

import pytest

from app.blocks.power_bi_connector import (
    PowerBiConnectorBlock,
    power_bi_kpi_rows,
)


def _configured_block():
    return PowerBiConnectorBlock(config={
        "RETAILOPS_POWERBI_TENANT_ID": "tenant-1",
        "RETAILOPS_POWERBI_CLIENT_ID": "client-1",
        "RETAILOPS_POWERBI_CLIENT_SECRET": "secret-1",
        "RETAILOPS_POWERBI_WORKSPACE_ID": "ws-1",
    })


@pytest.mark.asyncio
async def test_kpi_rows_are_deterministic_fiction():
    a = power_bi_kpi_rows("seed-1")
    b = power_bi_kpi_rows("seed-1")
    c = power_bi_kpi_rows("seed-2")
    assert a == b
    assert a != c
    assert len(a) == 14
    for row in a:
        assert row["store_id"].startswith("ST-")
        assert 4000 <= row["total_sales"] <= 22000


@pytest.mark.asyncio
async def test_pull_labels_source_as_mock():
    env = await PowerBiConnectorBlock().execute({"action": "pull", "cursor": "kpi-1"})
    assert env["status"] == "ok"
    body = env["result"]
    assert body["source"] == "mock"
    assert body["next_cursor"] == "powerbi-kpi-1-next"
    assert len(body["records"]) == 14


@pytest.mark.asyncio
async def test_normalize_maps_donor_fields():
    env = await PowerBiConnectorBlock().execute({
        "action": "normalize",
        "records": [{"date": "2026-07-01", "store_id": "ST-101", "total_sales": 5.0,
                     "transaction_count": 2, "stockout_events": 1, "supplier_delay_events": 0}],
    })
    assert env["status"] == "ok"
    rec = env["result"]["records"][0]
    assert rec["store"] == "ST-101"
    assert "store_id" not in rec


@pytest.mark.asyncio
async def test_export_csv_is_real_csv_bytes():
    rows = [
        {"date": "2026-07-01", "store_id": "ST-101", "total_sales": 5000.0,
         "transaction_count": 10, "stockout_events": 1, "supplier_delay_events": 0},
    ]
    env = await PowerBiConnectorBlock().execute({"action": "export_csv", "rows": rows})
    assert env["status"] == "ok"
    body = env["result"]
    assert body["status"] == "exported"
    assert body["row_count"] == 1
    decoded = base64.b64decode(body["content_base64"]).decode("utf-8")
    reader = csv.DictReader(io.StringIO(decoded))
    parsed = list(reader)
    assert parsed[0]["store_id"] == "ST-101"
    assert parsed[0]["total_sales"] == "5000.0"


@pytest.mark.asyncio
async def test_export_xlsx_is_real_xlsx_bytes():
    env = await PowerBiConnectorBlock().execute({"action": "export_xlsx", "cursor": "xlsx-1"})
    assert env["status"] == "ok"
    body = env["result"]
    assert body["row_count"] == 14
    raw = base64.b64decode(body["content_base64"])
    assert raw[:4] == b"PK\x03\x04"  # real zip/xlsx container
    assert body["content_type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.mark.asyncio
async def test_publish_dataset_refused_not_implemented():
    env = await PowerBiConnectorBlock().execute({"action": "publish_dataset", "rows": []})
    assert env["status"] == "refused"
    assert env["result"]["status"] == "not_implemented"
    assert "honest stub" in env["result"]["message"]


@pytest.mark.asyncio
async def test_refresh_semantic_model_refused_not_implemented():
    env = await PowerBiConnectorBlock().execute({"action": "refresh_semantic_model"})
    assert env["status"] == "refused"
    assert env["result"]["status"] == "not_implemented"


@pytest.mark.asyncio
async def test_get_embed_url_is_explicit_placeholder():
    env = await PowerBiConnectorBlock().execute({"action": "get_embed_url"})
    assert env["status"] == "ok"
    assert env["result"]["status"] == "placeholder"
    assert "PLACEHOLDER" in env["result"]["embed_url"]


@pytest.mark.asyncio
async def test_test_connection_unconfigured_reports_mock():
    env = await PowerBiConnectorBlock().execute({"action": "test_connection"})
    assert env["status"] == "ok"
    assert env["result"]["ok"] is True
    assert env["result"]["status"] == "mock"


@pytest.mark.asyncio
async def test_test_connection_configured_performs_real_aad_and_workspace_call(monkeypatch):
    captured = {}

    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"access_token": "tok-1"}

    class FakeClient:
        def __init__(self, timeout=30):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, data=None):
            captured["token_url"] = url
            captured["token_data"] = data
            return FakeResp()

        async def get(self, url, headers=None):
            captured["groups_url"] = url
            captured["groups_headers"] = headers
            return FakeResp()

    monkeypatch.setattr("httpx.AsyncClient", FakeClient)
    env = await _configured_block().execute({"action": "test_connection"})
    assert env["status"] == "ok"
    assert env["result"]["ok"] is True
    assert env["result"]["status"] == "connected"
    assert captured["token_url"] == "https://login.microsoftonline.com/tenant-1/oauth2/v2.0/token"
    assert captured["token_data"]["grant_type"] == "client_credentials"
    assert captured["token_data"]["client_id"] == "client-1"
    assert captured["groups_url"] == "https://api.powerbi.com/v1.0/myorg/groups/ws-1"
    assert captured["groups_headers"] == {"Authorization": "Bearer tok-1"}


@pytest.mark.asyncio
async def test_test_connection_configured_network_error_reported_honestly(monkeypatch):
    class BoomResp:
        def raise_for_status(self):
            raise RuntimeError("403 Forbidden")

        def json(self):
            return {"access_token": "tok-1"}

    class FakeClient:
        def __init__(self, timeout=30):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, data=None):
            return BoomResp()

        async def get(self, url, headers=None):
            return BoomResp()

    monkeypatch.setattr("httpx.AsyncClient", FakeClient)
    env = await _configured_block().execute({"action": "test_connection"})
    assert env["status"] == "ok"
    assert env["result"]["ok"] is False
    assert "403" in env["result"]["message"]


@pytest.mark.asyncio
async def test_unknown_action_error():
    env = await PowerBiConnectorBlock().execute({"action": "delete_workspace"})
    assert env["status"] == "error"
    assert "unknown action" in env["error"]
