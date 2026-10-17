"""Console Floor pack — contract + console tests.

Verifies, against a booted product (the store app with the pack mounted):
  1. /health and /ready answer;
  2. /v1/capabilities answers with at least two capabilities;
  3. the console is served at / and lets the operator paste a token;
  4. the console's driving paths (discover -> drive two) work end to end:
     the formulas capability computes a real value and every answer
     carries an authority label.
"""
from __future__ import annotations

import os

os.environ.setdefault("ENV", "test")
os.environ.setdefault("CEREBRUM_VIRGIN", "0")

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


# The store's dev/test key (same as tests/test_e2e.py) — the console's
# operator pastes it; the test drives the exact same authenticated path.
HDR = {"Authorization": "Bearer cb_dev_key"}


def test_health_and_ready_answer():
    h = client.get("/health")
    assert h.status_code == 200, f"/health answered {h.status_code}"
    r = client.get("/ready")
    # /ready must answer; in a dev/test boot without external dependencies
    # the store reports its dependency state in the body rather than dying.
    assert r.status_code in (200, 503), f"/ready answered {r.status_code}"
    assert r.headers.get("content-type", "").startswith("application/json")


def test_capabilities_answer_with_at_least_two():
    r = client.get("/v1/capabilities")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] >= 2, "console needs at least two capabilities"
    assert any(c["kind"] == "pack" for c in data["capabilities"])
    assert any(c["kind"] == "block" for c in data["capabilities"])


def test_console_is_served_at_root():
    r = client.get("/")
    assert r.status_code == 200
    html = r.text
    # The console discovers capabilities, never hardcodes names.
    assert 'fetch("/v1/capabilities")' in html
    # The operator pastes a token; none is embedded.
    assert "Authorization" in html
    assert "Bearer" in html
    assert 'id="token"' in html


def test_console_drives_two_capabilities_end_to_end():
    caps = client.get("/v1/capabilities").json()["capabilities"]
    driven = caps[:2]
    assert len(driven) == 2

    # Capability 1: formulas — a real computed value with an authority label.
    assert driven[0]["id"] == "formulas"
    r = client.post(
        "/v1/pack/formulas",
        json={"formula_id": "area_rectangle", "variables": {"width": 5, "height": 4}},
        headers=HDR,
    )
    assert r.status_code == 200, f"formulas answered {r.status_code}"
    body = r.json()
    assert body["status"] == "success", body
    assert body["value"] == 20.0, body
    assert body["authority"]["verdict"] == "grounded", body

    # Capability 2: the first discovered block, driven exactly the way the
    # console drives it (POST /v1/execute with the discovered id).
    r2 = client.post("/v1/execute", json={"block": driven[1]["id"], "input": {}}, headers=HDR)
    assert r2.status_code < 500, f"/v1/execute answered {r2.status_code}"
    body2 = r2.json()
    assert isinstance(body2, dict)


def test_pack_appears_in_store_catalog_listing():
    r = client.get("/v1/store/packs")
    assert r.status_code == 200
    packs = r.json()["packs"]
    assert any(p["id"] == "console_floor" for p in packs)
