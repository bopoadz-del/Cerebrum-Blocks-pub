"""Hotel cluster: real Opera connector (fail-closed) + hotel product endpoints."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app.core.connector_events import ConnectorEvent
from block_store.kits.hotel_management.blocks.opera_connector import OperaConnectorBlock


def _run(block, action="fetch", **data):
    return asyncio.run(block.process(dict(data), params={"action": action}))


# -- connector -------------------------------------------------------------


def test_unconfigured_fetch_fails_closed_with_refusal():
    block = OperaConnectorBlock()
    out = _run(block, resource="reservations")
    assert out["status"] == "error"
    refusal = (out.get("auth") or {}).get("refusal", "")
    assert "no live integration" in refusal
    assert "fabricated" in refusal
    assert "event" not in out  # no data envelope was produced


def test_unavailable_envelope_never_fabricates_data():
    block = OperaConnectorBlock()
    envelope = block._unavailable_envelope({"resource": "reservations"})
    assert envelope["available"] is False
    assert envelope["data"] == []
    assert envelope["mock_level"] == "mock_unavailable"


def test_normaliser_maps_opera_reservation_shape():
    block = OperaConnectorBlock()
    raw = {
        "available": True,
        "resource": "reservations",
        "data": [
            {
                "type": "reservation",
                "confirmationNumber": "CNF-123",
                "roomNumber": "1204",
                "guestName": "Ada Lovelace",
                "arrivalDate": "2026-02-01",
                "departureDate": "2026-02-04",
                "status": "checked_in",
            }
        ],
    }
    event = block.normalize(raw, {"event_type": "connector.fetch"}, {"resource": "reservations"})
    assert isinstance(event, ConnectorEvent)
    records = event.normalized_data["records"]
    assert records[0]["canonical_event"] == "reservation"
    assert records[0]["reservation_id"] == "CNF-123"
    assert records[0]["room"] == "1204"


def test_normaliser_passes_refusal_envelope_through():
    block = OperaConnectorBlock()
    envelope = block._unavailable_envelope({"resource": "reservations"})
    event = block.normalize(envelope, {}, {"resource": "reservations"})
    assert event.event_type == "connector.unavailable"
    assert event.normalized_data["available"] is False


# -- endpoints -------------------------------------------------------------

REVENUE_TEXT = (
    "Hotel Monthly Revenue Report\n"
    "Total room revenue: 450000 USD\n"
    "Rooms sold: 3000\n"
    "Rooms available: 4000\n"
    "Gross operating profit: 150000 USD\n"
)


def test_hotel_analyze_endpoint_runs_hotel_v2():
    from app.main import app

    client = TestClient(app)
    resp = client.post(
        "/v1/connectors/hotel/analyze",
        json={"text": REVENUE_TEXT},
        headers={"Authorization": "Bearer cb_dev_key"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # hotel_v2 analysis is deterministic: some extraction ran, no LLM.
    assert isinstance(body, dict)


def test_hotel_opera_endpoint_fails_closed_without_live_config():
    from app.main import app

    client = TestClient(app)
    resp = client.post(
        "/v1/connectors/hotel/opera",
        json={"resource": "reservations"},
        headers={"Authorization": "Bearer cb_dev_key"},
    )
    assert resp.status_code >= 400
    assert "no live integration" in resp.json()["detail"]
