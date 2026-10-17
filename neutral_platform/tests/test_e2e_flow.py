"""End-to-end flow through the real API (mission Phase 7 steps 1-15).

login -> tenant-scoped inspection -> deterministic rules -> risk score ->
maintenance action -> approval level -> correct-role approval -> one
approved transition -> one unsupported transition refused ->
evidence-grounded explanation -> XLSX/PDF -> verified audit chain.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from neutral_app import db
from neutral_app.main import app
from neutral_app.platform import reset_platform


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


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _critical_inspection_payload() -> dict:
    return {
        "equipment_id": "EQ-001",
        "condition": "poor",
        "likelihood": 4,
        "consequence": 4,
        "hours_since_service": 520,
        "service_interval_hours": 500,
        "equipment_class": "pump",
    }


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def scenario(client):
    """alice (t1) submits a critical inspection and gets a work order."""
    alice = _login(client, "u_alice")
    resp = client.post("/inspections", json=_critical_inspection_payload(), headers=_headers(alice))
    assert resp.status_code == 200, resp.text
    inspection = resp.json()["inspection"]
    wo = client.post(
        "/work_orders", json={"inspection_id": resp.json()["inspection_id"]}, headers=_headers(alice)
    ).json()
    return {
        "alice": alice,
        "bob": _login(client, "u_bob"),
        "carol": _login(client, "u_carol"),
        "dave": _login(client, "u_dave"),
        "eve": _login(client, "u_eve"),
        "inspection": inspection,
        "inspection_id": resp.json()["inspection_id"],
        "work_order_id": wo["work_order_id"],
    }


def test_login_and_wrong_credentials_refused(client):
    token = _login(client, "u_alice")
    assert token.count(".") == 1
    resp = client.get("/health")
    assert resp.json() == {"status": "ok"}
    bad = client.get(
        "/work_orders/whatever",
        headers={"Authorization": "Bearer tampered.token"},
    )
    assert bad.status_code == 401


def test_inspection_rules_risk_and_actions(client, scenario):
    inspection = scenario["inspection"]
    # Deterministic risk score: 4 x 4.
    assert inspection["risk_score"] == 16
    assert inspection["risk_band"] == "critical"
    actions = [a.get("decision", a.get("outcome")) for a in inspection["actions"]]
    assert any(a.get("action") == "create_work_order" for a in actions)
    assert any(a.get("action") == "immediate_work_order" for a in actions)
    assert inspection["explanation"], "explanation must be evidence-grounded and non-empty"


def test_refusal_rules(client):
    alice = _login(client, "u_alice")
    payload = _critical_inspection_payload()
    payload["equipment_class"] = "unknown"
    resp = client.post("/inspections", json=payload, headers=_headers(alice))
    assert resp.status_code == 422
    assert "unsupported equipment class" in resp.json()["detail"]["explanation"]

    payload = _critical_inspection_payload()
    payload["condition"] = "haunted"
    resp = client.post("/inspections", json=payload, headers=_headers(alice))
    assert resp.status_code == 422
    assert "unsupported condition" in resp.json()["detail"]["explanation"]


def test_tenant_isolation_404_not_403(client, scenario):
    eve = scenario["eve"]
    resp = client.get(f"/inspections/{scenario['inspection_id']}", headers=_headers(eve))
    assert resp.status_code == 404, "cross-tenant access must never leak existence"
    resp = client.get(f"/work_orders/{scenario['work_order_id']}", headers=_headers(eve))
    assert resp.status_code == 404


def test_workflow_roles_and_transitions(client, scenario):
    wo = scenario["work_order_id"]
    # Technician cannot schedule (supervisor-only transition).
    resp = client.post(
        f"/work_orders/{wo}/transition",
        json={"to_state": "scheduled", "evidence": {"schedule_note": "n/a"}},
        headers=_headers(scenario["dave"]),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "permission_denied"

    # Supervisor schedules with evidence.
    resp = client.post(
        f"/work_orders/{wo}/transition",
        json={"to_state": "scheduled", "evidence": {"schedule_note": "morning crew"}},
        headers=_headers(scenario["bob"]),
    )
    assert resp.json()["status"] == "success", resp.json()

    # Unsupported transition: scheduled -> closed is not declared.
    resp = client.post(
        f"/work_orders/{wo}/transition",
        json={"to_state": "closed", "evidence": {"closure_note": "skip everything"}},
        headers=_headers(scenario["bob"]),
    )
    assert resp.json()["status"] == "unsupported"

    # Technician starts (evidence required).
    resp = client.post(
        f"/work_orders/{wo}/transition",
        json={"to_state": "in_progress"},
        headers=_headers(scenario["dave"]),
    )
    assert resp.json()["status"] == "dependency_required"
    assert "evidence:start_time" in resp.json()["missing_inputs"]

    resp = client.post(
        f"/work_orders/{wo}/transition",
        json={"to_state": "in_progress", "evidence": {"start_time": "2026-09-17T08:00Z"}},
        headers=_headers(scenario["dave"]),
    )
    assert resp.json()["status"] == "success", resp.json()

    # Technician completes.
    resp = client.post(
        f"/work_orders/{wo}/transition",
        json={"to_state": "completed", "evidence": {"completion_note": "replaced seal"}},
        headers=_headers(scenario["dave"]),
    )
    assert resp.json()["status"] == "success", resp.json()

    # Closure requires an approval token.
    resp = client.post(
        f"/work_orders/{wo}/transition",
        json={"to_state": "closed", "evidence": {"closure_note": "verified"}},
        headers=_headers(scenario["bob"]),
    )
    assert resp.json()["status"] == "approval_required"


def test_approval_matrix(client, scenario):
    wo = scenario["work_order_id"]
    # Progress the order to completed before the approval dance.
    for actor, state, evidence in [
        (scenario["bob"], "scheduled", {"schedule_note": "crew"}),
        (scenario["dave"], "in_progress", {"start_time": "2026-09-17T08:00Z"}),
        (scenario["dave"], "completed", {"completion_note": "replaced seal"}),
    ]:
        resp = client.post(
            f"/work_orders/{wo}/transition",
            json={"to_state": state, "evidence": evidence},
            headers=_headers(actor),
        )
        assert resp.json()["status"] == "success", resp.json()
    # Alice requests closure approval — requirement is reported.
    resp = client.post(f"/work_orders/{wo}/close-approval", headers=_headers(scenario["alice"]))
    assert resp.status_code == 403, "alice is not an approver role"

    # Bob (supervisor) issues a token, but SoD pair (u_alice, u_bob) refuses
    # it at validation time.
    resp = client.post(f"/work_orders/{wo}/close-approval", headers=_headers(scenario["bob"]))
    assert resp.status_code == 200
    bob_token = resp.json()["token"]

    # Carol (maintenance_manager) issues a token — she is not in the SoD pair.
    resp = client.post(f"/work_orders/{wo}/close-approval", headers=_headers(scenario["carol"]))
    assert resp.status_code == 200
    carol_token = resp.json()["token"]

    # Bob's token is refused by the gate (SoD): closing with it fails.
    resp = client.post(
        f"/work_orders/{wo}/transition",
        json={"to_state": "closed", "evidence": {"closure_note": "verified"}, "approval_token": bob_token},
        headers=_headers(scenario["bob"]),
    )
    assert resp.json()["status"] == "approval_required", resp.json()

    # Carol's token closes the order.
    resp = client.post(
        f"/work_orders/{wo}/transition",
        json={"to_state": "closed", "evidence": {"closure_note": "verified"}, "approval_token": carol_token},
        headers=_headers(scenario["carol"]),
    )
    assert resp.json()["status"] == "success", resp.json()

    # Replay: the same token is consumed.
    resp = client.post(
        f"/work_orders/{wo}/transition",
        json={"to_state": "closed", "evidence": {"closure_note": "again"}, "approval_token": carol_token},
        headers=_headers(scenario["carol"]),
    )
    assert resp.json()["status"] == "approval_required", resp.json()
    assert any("replay" in r["reason"] for r in resp.json()["approval_refusals"])

    # Closed is immutable: no declared out-transition.
    resp = client.post(
        f"/work_orders/{wo}/transition",
        json={"to_state": "draft", "evidence": {}},
        headers=_headers(scenario["carol"]),
    )
    assert resp.json()["status"] == "unsupported"


def test_payload_binding_and_expiry(client, scenario):
    wo = scenario["work_order_id"]
    from neutral_app.platform import get_platform

    platform = get_platform()
    carol = {"id": "u_carol", "role": "maintenance_manager", "requester_id": "u_alice"}
    # Payload binding: a token minted for one payload fails a different one.
    token = platform.issue_approval(
        approver=carol,
        payload={"work_order_id": "wo-99999", "target_state": "closed"},
    )
    resp = client.post(
        f"/work_orders/{wo}/transition",
        json={"to_state": "closed", "evidence": {"closure_note": "x"}, "approval_token": token},
        headers=_headers(scenario["carol"]),
    )
    assert resp.json()["status"] == "approval_required"
    assert any("payload" in r["reason"] for r in resp.json()["approval_refusals"])

    # Expiry: a short-TTL token is refused after it lapses.
    token = platform.issue_approval(
        approver=carol,
        payload={"work_order_id": wo, "target_state": "closed"},
        ttl_seconds=1,
    )
    time.sleep(1.2)
    resp = client.post(
        f"/work_orders/{wo}/transition",
        json={"to_state": "closed", "evidence": {"closure_note": "x"}, "approval_token": token},
        headers=_headers(scenario["carol"]),
    )
    assert resp.json()["status"] == "approval_required"
    assert any("expired" in r["reason"] for r in resp.json()["approval_refusals"])


def test_low_risk_work_order_can_be_cancelled_by_requester(client):
    alice = _login(client, "u_alice")
    payload = {
        "equipment_id": "EQ-002",
        "condition": "good",
        "likelihood": 2,
        "consequence": 2,
        "hours_since_service": 520,
        "service_interval_hours": 500,
        "equipment_class": "pump",
    }
    resp = client.post("/inspections", json=payload, headers=_headers(alice))
    inspection = resp.json()["inspection"]
    assert inspection["risk_score"] == 4
    assert inspection["risk_band"] == "medium"
    # Below the critical threshold, the service-interval rule is the
    # winning action (kernel precedence: the critical rule subsumes at 15+).
    actions = [a.get("decision", a.get("outcome")) for a in inspection["actions"]]
    assert any(a.get("action") == "schedule_service" for a in actions)
    wo = client.post(
        "/work_orders", json={"inspection_id": resp.json()["inspection_id"]}, headers=_headers(alice)
    ).json()
    resp = client.post(
        f"/work_orders/{wo['work_order_id']}/transition",
        json={"to_state": "cancelled"},
        headers=_headers(alice),
    )
    assert resp.json()["status"] == "success", resp.json()


def test_critical_work_order_cannot_be_cancelled_by_requester(client, scenario):
    # The draft->cancelled guard refuses critical-risk orders.
    resp = client.post(
        f"/work_orders/{scenario['work_order_id']}/transition",
        json={"to_state": "cancelled"},
        headers=_headers(scenario["alice"]),
    )
    assert resp.json()["status"] == "validation_error"
    assert "guard" in resp.json()["explanation"]


def test_self_approval_refused(client):
    # Bob (supervisor) submits his own inspection, then tries to approve
    # closure of his own work order — self-approval is prohibited.
    bob = _login(client, "u_bob")
    payload = {
        "equipment_id": "EQ-003",
        "condition": "fair",
        "likelihood": 3,
        "consequence": 3,
        "hours_since_service": 100,
        "service_interval_hours": 500,
        "equipment_class": "pump",
    }
    resp = client.post("/inspections", json=payload, headers=_headers(bob))
    wo = client.post(
        "/work_orders", json={"inspection_id": resp.json()["inspection_id"]}, headers=_headers(bob)
    ).json()
    resp = client.post(
        f"/work_orders/{wo['work_order_id']}/close-approval", headers=_headers(bob)
    )
    assert resp.status_code == 403
    assert "self-approval" in resp.json()["detail"]["explanation"]


def test_reports_and_audit_chain(client, scenario):
    wo = scenario["work_order_id"]
    # Bring the order to closed so the report shows the full history.
    for actor, state, evidence in [
        (scenario["bob"], "scheduled", {"schedule_note": "crew"}),
        (scenario["dave"], "in_progress", {"start_time": "2026-09-17T08:00Z"}),
        (scenario["dave"], "completed", {"completion_note": "done"}),
    ]:
        client.post(
            f"/work_orders/{wo}/transition",
            json={"to_state": state, "evidence": evidence},
            headers=_headers(actor),
        )
    resp = client.post(f"/work_orders/{wo}/close-approval", headers=_headers(scenario["alice"]))
    assert resp.status_code == 403  # requester is not an approver role
    resp = client.post(f"/work_orders/{wo}/close-approval", headers=_headers(scenario["carol"]))
    token = resp.json()["token"]
    resp = client.post(
        f"/work_orders/{wo}/transition",
        json={"to_state": "closed", "evidence": {"closure_note": "verified"}, "approval_token": token},
        headers=_headers(scenario["carol"]),
    )
    assert resp.json()["status"] == "success", resp.json()

    # XLSX report.
    resp = client.get(f"/work_orders/{wo}/report.xlsx", headers=_headers(scenario["alice"]))
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/vnd.openxml")
    from io import BytesIO

    wb = load_workbook(BytesIO(resp.content))
    values = [str(c.value) for row in wb.active.iter_rows() for c in row if c.value]
    assert any("EQ-001" in v for v in values)
    assert any("critical" in v for v in values)

    # PDF report.
    resp = client.get(f"/work_orders/{wo}/report.pdf", headers=_headers(scenario["alice"]))
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content[:5] == b"%PDF-"

    # Audit chain verifies end-to-end.
    resp = client.get(f"/work_orders/{wo}/audit", headers=_headers(scenario["alice"]))
    body = resp.json()
    assert body["chain"]["verified"] is True
    assert body["chain"]["events"] >= 8
    hashes = [e["record_hash"] for e in body["events"]]
    assert len(set(hashes)) == len(hashes), "audit hashes must be unique per event"


def test_tenant_audit_is_isolated(client, scenario):
    eve = scenario["eve"]
    resp = client.get(f"/work_orders/{scenario['work_order_id']}/audit", headers=_headers(eve))
    assert resp.status_code == 404
