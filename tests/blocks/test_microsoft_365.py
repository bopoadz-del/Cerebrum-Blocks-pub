"""Microsoft 365 Graph integration â€” ported Cerebrum microsoft_365.py.

Offline tests: the fail-closed credential gate (no usable token / no client
credentials / missing settings -> structured refusal), the in-process
connection store, and the donor's request shaping verified with a
monkeypatched requests layer (never the live Graph endpoint).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.blocks import microsoft_365 as m365


def _run(coro):
    return asyncio.run(coro)


def _p(b, payload):
    return _run(b.process(payload))


@pytest.fixture
def block():
    return m365.Microsoft365Block()


def _conn(payload_extra=None):
    base = {"organization_id": "org-1", "access_token": "tok", "token_expires_at": "2027-01-01T00:00:00"}
    if payload_extra:
        base.update(payload_extra)
    return base


# -- store + credential gate ---------------------------------------------------

def test_create_and_get_connection(block):
    r = _p(block, {"action": "create_connection", "connection_id": "c1", **_conn()})
    assert r["status"] == "ok"
    assert r["result"]["connection"]["id"] == "c1"
    g = _p(block, {"action": "get_connection", "connection_id": "c1"})
    assert g["status"] == "ok"
    assert g["result"]["connection"]["organization_id"] == "org-1"


def test_connection_without_token_refuses_before_network(block):
    _p(block, {"action": "create_connection", "connection_id": "c2", "organization_id": "org-2"})
    r = _p(block, {"action": "get_user_profile", "connection_id": "c2"})
    assert r["status"] == "refused"
    assert "no usable access token" in r["error"]


def test_expired_token_without_client_credentials_refuses(block):
    _p(block, {"action": "create_connection", "connection_id": "c3", "organization_id": "org-3",
               "access_token": "tok", "refresh_token": "rtok",
               "token_expires_at": "2020-01-01T00:00:00"})
    r = _p(block, {"action": "get_user_profile", "connection_id": "c3"})
    assert r["status"] == "refused"
    assert "MICROSOFT365_CLIENT_ID" in r["error"]


def test_inactive_connection_refuses(block):
    _p(block, {"action": "create_connection", "connection_id": "c4", **_conn(), "is_active": False})
    r = _p(block, {"action": "get_user_profile", "connection_id": "c4"})
    assert r["status"] == "refused"
    assert "inactive" in r["error"]


def test_unknown_connection_and_action(block):
    assert _p(block, {"action": "get_user_profile", "connection_id": "zz"})["status"] == "error"
    _p(block, {"action": "create_connection", "connection_id": "c5", **_conn()})
    assert _p(block, {"action": "bogus", "connection_id": "c5"})["status"] == "error"


def test_teams_actions_need_team_id_in_settings(block):
    _p(block, {"action": "create_connection", "connection_id": "c6", **_conn(), "settings": {}})
    r = _p(block, {"action": "send_teams_message", "connection_id": "c6", "channel_id": "ch", "message": "hi"})
    assert r["status"] == "refused"
    assert "team_id" in r["error"]
    r = _p(block, {"action": "get_teams_channels", "connection_id": "c6"})
    assert r["status"] == "refused"


def test_sharepoint_actions_need_site_and_drive(block):
    _p(block, {"action": "create_connection", "connection_id": "c7", **_conn(), "settings": {"team_id": "t"}})
    r = _p(block, {"action": "create_sharepoint_folder", "connection_id": "c7", "folder": {"folder_name": "f"}})
    assert r["status"] == "refused"
    assert "site_id" in r["error"]


def test_invalid_meeting_payload_is_an_error(block):
    _p(block, {"action": "create_connection", "connection_id": "c8", **_conn()})
    r = _p(block, {"action": "create_teams_meeting", "connection_id": "c8", "meeting": {"title": "x"}})
    assert r["status"] == "error"


def test_upload_requires_bytes(block):
    _p(block, {"action": "create_connection", "connection_id": "c9", **_conn(),
               "settings": {"site_id": "s", "drive_id": "d"}})
    r = _p(block, {"action": "upload_sharepoint_file", "connection_id": "c9",
                   "folder_id": "f", "file_name": "x.txt", "file_content": 12345})
    assert r["status"] == "error"
    assert "bytes" in r["error"]


# -- donor request shaping (monkeypatched requests, offline) -------------------

class _FakeResponse:
    def __init__(self, payload=None, status=200):
        self._payload = payload or {"id": "meet-1", "joinUrl": "https://teams/join"}
        self.status_code = status
        self.content = b"{}"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_create_teams_meeting_builds_graph_payload(block, monkeypatch):
    calls = []

    def fake_post(url, headers=None, json=None, data=None):
        calls.append({"url": url, "headers": headers, "json": json})
        return _FakeResponse()

    monkeypatch.setattr(m365.requests, "post", fake_post)
    _p(block, {"action": "create_connection", "connection_id": "c10", **_conn()})
    r = _p(block, {"action": "create_teams_meeting", "connection_id": "c10",
                   "meeting": {"title": "sync", "start_time": "2026-07-01T10:00:00",
                               "end_time": "2026-07-01T11:00:00",
                               "attendees": ["a@x.com", "b@x.com"], "description": "d"}})
    assert r["status"] == "ok"
    assert r["result"]["meeting"]["id"] == "meet-1"
    assert len(calls) == 1
    call = calls[0]
    assert call["url"] == "https://graph.microsoft.com/v1.0/me/onlineMeetings"
    assert call["headers"]["Authorization"] == "Bearer tok"
    participants = call["json"]["participants"]["attendees"]
    assert [a["emailAddress"]["address"] for a in participants] == ["a@x.com", "b@x.com"]
    assert call["json"]["subject"] == "sync"


def test_create_outlook_event_builds_graph_payload(block, monkeypatch):
    calls = []

    def fake_post(url, headers=None, json=None, data=None):
        calls.append({"url": url, "json": json})
        return _FakeResponse({"id": "ev-1"})

    monkeypatch.setattr(m365.requests, "post", fake_post)
    _p(block, {"action": "create_connection", "connection_id": "c11", **_conn()})
    r = _p(block, {"action": "create_outlook_event", "connection_id": "c11",
                   "event": {"subject": "review", "start_time": "2026-07-01T10:00:00",
                             "end_time": "2026-07-01T11:00:00", "location": "L2"}})
    assert r["status"] == "ok"
    call = calls[0]
    assert call["url"] == "https://graph.microsoft.com/v1.0/me/events"
    assert call["json"]["subject"] == "review"
    assert call["json"]["location"] == {"displayName": "L2"}
    assert call["json"]["start"]["timeZone"] == "UTC"


def test_upstream_failure_surfaces_as_error_envelope(block, monkeypatch):
    def fake_get(url, headers=None):
        return _FakeResponse(status=401)

    monkeypatch.setattr(m365.requests, "get", fake_get)
    _p(block, {"action": "create_connection", "connection_id": "c12", **_conn()})
    r = _p(block, {"action": "get_user_profile", "connection_id": "c12"})
    assert r["status"] == "error"
    assert "401" in r["error"]


def test_token_usable_logic():
    now = datetime(2026, 7, 1, tzinfo=timezone.utc).replace(tzinfo=None)
    conn = m365.Microsoft365Connection(id="x", access_token="t", token_expires_at=None)
    assert m365._token_usable(conn, now) is True
    conn.token_expires_at = now + timedelta(hours=1)
    assert m365._token_usable(conn, now) is True
    conn.token_expires_at = now - timedelta(hours=1)
    assert m365._token_usable(conn, now) is False
    conn.access_token = None
    assert m365._token_usable(conn, now) is False
