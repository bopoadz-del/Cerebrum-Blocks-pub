"""Liveness, readiness, and diagnostics boundaries.

Three defects are pinned here:

1. `/health` was unauthenticated and shelled out to the Kimi CLI on every
   hit, returning subprocess stdout, subprocess stderr, and the raw value
   of the KIMI_CLI_PATH env var to any caller. Render polls it
   continuously.
2. `/health` returned "healthy" unconditionally, so a service with an
   unwritable data disk was indistinguishable from a working one and the
   platform health check could never fail.
3. `/stats` returned the same block inventory that `/blocks` is
   deliberately auth-gated to protect, nullifying that gate.

The shapes below therefore assert on what an *unauthenticated* caller can
observe — the response bytes and the side effects — rather than on how the
router is wired internally. The original capability semantic ("a
registered block is not a capability unless the CLI actually answers") is
preserved, but exercised against the authenticated diagnostics endpoint
and with a mocked subprocess, so it no longer depends on being able to
execute a `#!/bin/sh` script (which never worked on Windows).
"""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import blocks as blocks_router
from app.routers import health as health_router


DEV_KEY = "cb_dev_key"  # tests/conftest.py sets ENV=test, which loads it
AUTH_HEADER = {"Authorization": f"Bearer {DEV_KEY}"}


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(health_router.router)
    app.include_router(blocks_router.router)
    health_router.reset_kimi_probe_cache()
    with TestClient(app) as test_client:
        yield test_client
    health_router.reset_kimi_probe_cache()


def _completed(returncode=0, stdout="kimi 1.2.3", stderr=""):
    return subprocess.CompletedProcess(
        args=["kimi", "--version"], returncode=returncode, stdout=stdout, stderr=stderr
    )


# ── /version is a deploy fact, not a secret ───────────────────────────────

def test_version_is_unauthenticated_and_closed(client, monkeypatch):
    """Public, names the service, closed key set. Handler-only tests live
    in tests/test_version_endpoint.py so the Full suite never opens a
    TestClient from that late file (PR #112 deadlock)."""
    monkeypatch.setenv("RENDER_GIT_COMMIT", "a" * 40)
    response = client.get("/version")
    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "cerebrum-blocks"
    assert body["git_sha"] == "a" * 40
    assert body["git_sha_short"] == "a" * 7
    assert set(body) == {"service", "git_sha", "git_sha_short", "env"}


def test_unknown_version_is_null_not_invented(client, monkeypatch):
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    monkeypatch.delenv("GIT_COMMIT", raising=False)
    monkeypatch.setattr(health_router, "_build_sha", lambda: None)
    body = client.get("/version").json()
    assert body["git_sha"] is None
    assert body["git_sha_short"] is None


# ── Liveness stays cheap and says nothing ─────────────────────────────────

@pytest.mark.parametrize("path", ["/health", "/v1/health"])
def test_liveness_is_unauthenticated_and_minimal(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize("path", ["/health", "/v1/health"])
def test_liveness_reveals_no_internals(client, path):
    """The generalising guard: no inventory, no counts, no host paths, no
    tooling names — whatever future fields get added."""
    body = client.get(path).text
    for leak in ("blocks_", "kimi", "registry", "version", "path", "error"):
        assert leak not in body.lower(), f"liveness body leaks {leak!r}: {body}"


@pytest.mark.parametrize("path", ["/health", "/v1/health"])
def test_liveness_spawns_no_subprocess(client, path):
    """Render probes this every few seconds; a process spawn per probe is a
    free denial-of-service primitive."""
    with patch.object(health_router.subprocess, "run") as spawn:
        spawn.return_value = _completed()
        for _ in range(5):
            assert client.get(path).status_code == 200
    assert spawn.call_count == 0


# ── Readiness can actually fail ───────────────────────────────────────────

@pytest.mark.parametrize("path", ["/ready", "/v1/ready"])
def test_readiness_passes_when_dependencies_are_healthy(client, path, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    response = client.get(path)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["data_dir"] == "ok"
    assert body["checks"]["block_registry"] == "ok"


@pytest.mark.parametrize("path", ["/ready", "/v1/ready"])
def test_readiness_returns_non_200_when_data_dir_is_unwritable(
    client, path, tmp_path, monkeypatch
):
    """Point DATA_DIR at an existing regular file: makedirs cannot turn it
    into a directory, on Windows or Unix. Without a non-2xx here the
    platform health check can never detect a broken service."""
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("DATA_DIR", str(blocker))

    response = client.get(path)
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["checks"]["data_dir"] == "fail"


def test_readiness_is_stable_under_concurrent_probes(client, tmp_path, monkeypatch):
    """Render's health checker and the Docker HEALTHCHECK overlap. A probe
    that used a shared temp filename would race with itself and report a
    false "degraded" — which now fails a deploy."""
    import concurrent.futures

    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: client.get("/ready").status_code, range(40)))
    assert set(results) == {200}, f"readiness flapped under concurrency: {set(results)}"


def test_readiness_leaves_no_probe_files_behind(client, tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    for _ in range(5):
        client.get("/ready")
    leftovers = [p.name for p in data_dir.iterdir()]
    assert leftovers == [], f"readiness probe left files behind: {leftovers}"


def test_degraded_readiness_body_leaks_nothing(client, tmp_path, monkeypatch):
    """Readiness is unauthenticated, so its failure path must not become a
    new disclosure channel — no host paths, no exception text."""
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("DATA_DIR", str(blocker))

    body = client.get("/ready").text
    assert str(blocker) not in body
    assert str(tmp_path) not in body
    assert "not-a-directory" not in body
    for leak in ("Traceback", "Errno", "NotADirectory", "FileExists", "WinError"):
        assert leak not in body


# ── Inventory is gated consistently ───────────────────────────────────────

@pytest.mark.parametrize(
    "path",
    ["/stats", "/blocks", "/v1/blocks", "/v1/system/diagnostics", "/v1/system/health"],
)
def test_inventory_and_diagnostics_require_auth(client, path):
    assert client.get(path).status_code == 401


def test_liveness_does_not_expose_the_inventory_that_blocks_gates(client):
    """The specific defect: /stats returned the identical inventory that
    /blocks is auth-gated to protect. Whatever else liveness grows, it must
    never carry block names."""
    body = client.get("/health").text
    for name in ("secrets", "code", "sandbox", "database", "webhook", "chat"):
        assert name not in body


def test_stats_serves_the_inventory_once_authenticated(client):
    response = client.get("/stats", headers=AUTH_HEADER)
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["blocks"], list)
    assert payload["total_blocks"] > 0


# ── Diagnostics: capability is evaluated, not assumed ─────────────────────

def test_diagnostics_reports_capability_when_cli_answers(client):
    with patch.object(health_router.subprocess, "run", return_value=_completed()):
        body = client.get("/v1/system/diagnostics", headers=AUTH_HEADER).json()
    probe = body["kimi_workbench"]
    assert probe["cli_ok"] is True
    assert probe["cli_version"] == "kimi 1.2.3"


def test_diagnostics_reports_no_capability_when_cli_is_absent(client):
    with patch.object(health_router.subprocess, "run", side_effect=FileNotFoundError()):
        body = client.get("/v1/system/diagnostics", headers=AUTH_HEADER).json()
    probe = body["kimi_workbench"]
    assert probe["cli_ok"] is False
    assert probe["registered"] is True


def test_probe_failure_never_echoes_the_cli_path_or_stderr(monkeypatch):
    """The original code returned f"CLI not found: {cli}" and raw stderr,
    disclosing host filesystem layout and internal error text."""
    secret_path = "/opt/" + __import__("secrets").token_hex(16) + "/cli"
    monkeypatch.setenv("KIMI_CLI_PATH", secret_path)

    health_router.reset_kimi_probe_cache()
    with patch.object(health_router.subprocess, "run", side_effect=FileNotFoundError()):
        missing = health_router.probe_kimi_cli(force=True)

    health_router.reset_kimi_probe_cache()
    with patch.object(
        health_router.subprocess,
        "run",
        return_value=_completed(returncode=1, stderr="ldd: /lib/x86_64/libSENTINEL.so missing"),
    ):
        failing = health_router.probe_kimi_cli(force=True)

    health_router.reset_kimi_probe_cache()
    for probe in (missing, failing):
        blob = str(probe)
        assert "SENTINEL" not in blob
        assert secret_path not in blob


def test_kimi_probe_is_cached_off_the_request_path(client):
    """Whatever endpoint exposes it, the probe must not spawn a process per
    call."""
    health_router.reset_kimi_probe_cache()
    with patch.object(health_router.subprocess, "run") as spawn:
        spawn.return_value = _completed()
        for _ in range(4):
            assert (
                client.get("/v1/system/diagnostics", headers=AUTH_HEADER).status_code
                == 200
            )
    assert spawn.call_count == 1
