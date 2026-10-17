"""PostgreSQL execution of the same E2E flow (mission: "Run in PostgreSQL").

Skips unless NEUTRAL_DB_URL points at PostgreSQL — the GitHub Actions
workflow provides a postgres:16 service and runs this file with the URL
set. Running it accidentally against sqlite is refused, not silently
passed: the whole point of this file is the PostgreSQL evidence.
"""

from __future__ import annotations

import os

import pytest

needed = os.environ.get("NEUTRAL_DB_URL", "")
if not needed.startswith("postgres"):
    pytest.skip(
        "NEUTRAL_DB_URL is not a PostgreSQL URL — CI runs this against "
        "the postgres service container",
        allow_module_level=True,
    )

from fastapi.testclient import TestClient  # noqa: E402

from neutral_app import db  # noqa: E402
from neutral_app.main import app  # noqa: E402
from neutral_app.platform import reset_platform  # noqa: E402


@pytest.fixture(autouse=True)
def clean_state():
    reset_platform()
    db.reset_db_engine()
    engine = db.get_engine()
    db.Base.metadata.drop_all(engine)
    db.Base.metadata.create_all(engine)
    yield
    reset_platform()
    db.reset_db_engine()


def _login(client: TestClient, user: str) -> str:
    resp = client.post("/login", json={"user_id": user})
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


def test_full_flow_on_postgres():
    assert db.get_engine().dialect.name == "postgresql"
    with TestClient(app) as client:
        alice = _login(client, "u_alice")
        bob = _login(client, "u_bob")
        carol = _login(client, "u_carol")
        dave = _login(client, "u_dave")
        headers = {"Authorization": f"Bearer {alice}"}
        payload = {
            "equipment_id": "EQ-PG-01",
            "condition": "poor",
            "likelihood": 4,
            "consequence": 4,
            "hours_since_service": 520,
            "service_interval_hours": 500,
            "equipment_class": "pump",
        }
        resp = client.post("/inspections", json=payload, headers=headers)
        assert resp.status_code == 200, resp.text
        inspection_id = resp.json()["inspection_id"]
        assert resp.json()["inspection"]["risk_score"] == 16

        wo = client.post(
            "/work_orders", json={"inspection_id": inspection_id}, headers=headers
        ).json()
        wo_id = wo["work_order_id"]
        for actor, state, evidence in [
            (bob, "scheduled", {"schedule_note": "crew"}),
            (dave, "in_progress", {"start_time": "2026-09-17T08:00Z"}),
            (dave, "completed", {"completion_note": "done"}),
        ]:
            resp = client.post(
                f"/work_orders/{wo_id}/transition",
                json={"to_state": state, "evidence": evidence},
                headers={"Authorization": f"Bearer {actor}"},
            )
            assert resp.json()["status"] == "success", resp.json()

        token = client.post(
            f"/work_orders/{wo_id}/close-approval",
            headers={"Authorization": f"Bearer {carol}"},
        ).json()["token"]
        resp = client.post(
            f"/work_orders/{wo_id}/transition",
            json={"to_state": "closed", "evidence": {"closure_note": "ok"}, "approval_token": token},
            headers={"Authorization": f"Bearer {carol}"},
        )
        assert resp.json()["status"] == "success", resp.json()

        audit = client.get(f"/work_orders/{wo_id}/audit", headers=headers).json()
        assert audit["chain"]["verified"] is True

        xlsx = client.get(f"/work_orders/{wo_id}/report.xlsx", headers=headers)
        assert xlsx.status_code == 200
