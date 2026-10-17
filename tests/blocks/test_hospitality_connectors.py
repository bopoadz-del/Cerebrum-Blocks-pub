"""hospitality_connectors: donor pipeline parity + refusal paths.

Donor: <private-repo> connectors/base.py + connectors/{opera,micros,
maximo,grms,gaming_cms,loyalty_lms}.py + hotelops/event_bus.py.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.blocks.hospitality_connectors import (
    ConnectorError,
    HospitalityConnectorsBlock,
)


def _run(coro):
    return asyncio.run(coro)


def _block(config=None):
    return HospitalityConnectorsBlock(config=config)


def test_systems_listing():
    r = _run(_block().execute({"action": "systems"}))
    assert r["status"] == "ok"
    assert set(r["result"]["systems"]) == {"opera", "micros", "maximo", "grms", "gaming_cms", "loyalty_lms"}


def test_opera_reservations_ingest_fixture():
    b = _block()
    r = _run(b.execute({"action": "ingest", "system": "opera", "resource": "reservations"}))
    assert r["status"] == "ok"
    res = r["result"]
    assert res["mode"] == "fixture"
    assert res["emitted"] == 3
    topics = {e["topic"] for e in res["events"]}
    assert topics == {"guest.booking.reservation"}
    first = res["events"][0]
    assert first["source"] == "opera_pms"
    assert first["surface"] == "guest"
    assert first["payload"]["confirmation_id"] == "CNF-DXB-1001"
    assert first["payload"]["market"] == "uae"


def test_opera_fetch_id_filter():
    b = _block()
    r = _run(b.execute({"action": "fetch", "system": "opera", "resource": "reservations", "id": "R-1003"}))
    assert r["status"] == "ok"
    assert r["result"]["data"]["confirmation_id"] == "CNF-DXB-1003"


def test_opera_housekeeping_and_in_house_topics():
    b = _block()
    hk = _run(b.execute({"action": "ingest", "system": "opera", "resource": "housekeeping"}))
    assert {e["topic"] for e in hk["result"]["events"]} == {"ops.pms.housekeeping"}
    ih = _run(b.execute({"action": "ingest", "system": "opera", "resource": "in_house"}))
    assert {e["topic"] for e in ih["result"]["events"]} == {"ops.pms.in_house"}
    assert ih["result"]["events"][0]["payload"]["vip"] is True


def test_micros_checks_folio_charge():
    b = _block()
    r = _run(b.execute({"action": "ingest", "system": "micros", "resource": "checks"}))
    assert r["status"] == "ok"
    ev = r["result"]["events"][0]
    assert ev["topic"] == "guest.folio.charge"
    assert ev["payload"]["amount"] == 128.5


def test_maximo_assets_ingest():
    b = _block()
    r = _run(b.execute({"action": "ingest", "system": "maximo", "resource": "assets"}))
    assert r["status"] == "ok"
    events = r["result"]["events"]
    assert {e["topic"] for e in events} == {"ops.engineering.asset"}
    assert events[0]["evidence_class"] == "A"
    assert events[0]["payload"]["asset_id"] == "FP-01"
    assert events[0]["payload"]["statutory_flag"] is True
    assert events[2]["payload"]["source_system"] == "csv_upload"


def test_maximo_workorders_topic():
    b = _block()
    r = _run(b.execute({"action": "ingest", "system": "maximo", "resource": "workorders"}))
    assert {e["topic"] for e in r["result"]["events"]} == {"ops.cmms.workorder"}
    assert r["result"]["events"][0]["payload"]["wo"] == "WO-501"


def test_maximo_aconex_asset_refused():
    b = _block()
    raw = {"records": [{"asset_id": "X-1", "source_system": "aconex"}]}
    r = _run(b.execute({"action": "normalise", "system": "maximo", "resource": "assets", "raw": raw}))
    assert r["status"] == "refused"
    assert "out of scope" in r["detail"]["message"]


def test_maximo_procore_asset_refused():
    b = _block()
    raw = {"records": [{"asset_id": "X-1", "source_system": "procore"}]}
    r = _run(b.execute({"action": "normalise", "system": "maximo", "resource": "assets", "raw": raw}))
    assert r["status"] == "refused"


def test_grms_config_complete_passes():
    b = _block()
    r = _run(b.execute({"action": "ingest", "system": "grms", "resource": "config"}))
    ev = r["result"]["events"][0]
    assert ev["topic"] == "ops.engineering.grms_config"
    assert ev["verdict"] == "PASS"
    assert ev["evidence_class"] == "A"
    assert ev["payload"]["room_map_complete"] is True


def test_grms_config_incomplete_unprovable():
    b = _block()
    # The donor's config_incomplete fixture is judged through the config
    # resource (the normalise branch keys on resource == "config").
    from app.blocks.hospitality_connectors import FIXTURES
    r = _run(b.execute({"action": "normalise", "system": "grms", "resource": "config", "raw": FIXTURES["grms"]["config_incomplete"]}))
    ev = r["result"]["events"][0]
    assert ev["verdict"] == "UNPROVABLE"
    assert ev["evidence_class"] == "Unprovable"
    assert "INV-GRMS-ROOM-MAP" in ev["payload"]["invalidity_ids"]
    assert ev["payload"]["room_map_complete"] is False


def test_grms_rooms_topic():
    b = _block()
    r = _run(b.execute({"action": "ingest", "system": "grms", "resource": "rooms"}))
    assert {e["topic"] for e in r["result"]["events"]} == {"ops.grms.room"}


def test_gaming_cms_comps():
    b = _block()
    r = _run(b.execute({"action": "ingest", "system": "gaming_cms", "resource": "players"}))
    ev = r["result"]["events"][0]
    assert ev["topic"] == "guest.gaming.comp"
    assert ev["payload"]["comp_balance"] == 320.0


def test_loyalty_lms_profiles():
    b = _block()
    r = _run(b.execute({"action": "ingest", "system": "loyalty_lms", "resource": "profiles"}))
    ev = r["result"]["events"][0]
    assert ev["topic"] == "guest.loyalty.profile"
    assert ev["payload"]["tier"] == "gold"


def test_unknown_system_refused():
    b = _block()
    r = _run(b.execute({"action": "ingest", "system": "sabre", "resource": "reservations"}))
    assert r["status"] == "refused"
    assert "unknown system" in r["detail"]["message"]


def test_missing_fixture_refused():
    b = _block()
    r = _run(b.execute({"action": "ingest", "system": "opera", "resource": "profiles"}))
    assert r["status"] == "refused"
    assert "missing" in r["detail"]["message"]


def test_fetch_missing_id_refused():
    b = _block()
    r = _run(b.execute({"action": "fetch", "system": "opera", "resource": "reservations", "id": "NOPE"}))
    assert r["status"] == "refused"
    assert "not in" in r["detail"]["message"]


def test_live_url_unconfigured_refused():
    b = _block()
    with pytest.raises(ConnectorError) as excinfo:
        b._connector("maximo").live_url("assets")
    assert "live URL not configured" in str(excinfo.value)
    with pytest.raises(ConnectorError) as excinfo:
        b._connector("opera").live_url("reservations")
    assert "live URL not configured" in str(excinfo.value)


def test_incomplete_live_keys_stay_fixture():
    b = _block(config={"fixture_mode": False, "maximo_base_url": "http://x", "maximo_api_key": ""})
    r = _run(b.execute({"action": "connect", "system": "maximo"}))
    assert r["result"]["mode"] == "fixture"


def test_full_live_keys_connect_live():
    b = _block(config={"fixture_mode": False, "maximo_base_url": "http://127.0.0.1:9", "maximo_api_key": "k"})
    r = _run(b.execute({"action": "connect", "system": "maximo"}))
    assert r["result"]["mode"] == "live"


def test_live_http_failure_refused(monkeypatch):
    b = _block(config={"fixture_mode": False, "maximo_base_url": "http://127.0.0.1:9", "maximo_api_key": "k"})

    def _boom(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", _boom)
    r = _run(b.execute({"action": "fetch", "system": "maximo", "resource": "assets"}))
    assert r["status"] == "refused"
    assert r["error"] == "live_http_failed"


def test_bus_history_with_filters():
    b = _block()
    _run(b.execute({"action": "ingest", "system": "opera", "resource": "reservations"}))
    _run(b.execute({"action": "ingest", "system": "maximo", "resource": "workorders"}))
    all_events = _run(b.execute({"action": "bus"}))["result"]["events"]
    assert len(all_events) == 4
    guest = _run(b.execute({"action": "bus", "surface": "guest"}))["result"]["events"]
    assert len(guest) == 3
    wo = _run(b.execute({"action": "bus", "topic_prefix": "ops.cmms"}))["result"]["events"]
    assert len(wo) == 1 and wo[0]["topic"] == "ops.cmms.workorder"


def test_normalise_action_with_raw():
    b = _block()
    raw = {"records": [{"id": "X", "room": "9", "hk_status": "clean"}]}
    r = _run(b.execute({"action": "normalise", "system": "opera", "resource": "housekeeping", "raw": raw}))
    assert r["status"] == "ok"
    assert r["result"]["events"][0]["topic"] == "ops.pms.housekeeping"


def test_unknown_action_error():
    b = _block()
    r = _run(b.execute({"action": "push"}))
    assert r["status"] == "error"
    assert "unknown action" in r["error"]


@pytest.mark.asyncio
async def test_process_is_async_coroutine():
    b = _block()
    r = await b.process({"action": "ingest", "system": "loyalty_lms", "resource": "profiles"})
    assert r["status"] == "ok"
    assert r["result"]["events"][0]["payload"]["profile_id"] == "L-4"
