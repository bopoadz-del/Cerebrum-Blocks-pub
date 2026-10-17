"""Subprocess env guard tests - ported behavior from The_Fork subprocess_env.py."""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("ENV", "test")

from app.blocks.subprocess_env_guard import (
    SubprocessEnvGuardBlock,
    is_secret_env_name,
    scrubbed_env,
)


def _run(coro):
    return asyncio.run(coro)


def test_exact_and_pattern_secret_names_detected():
    for name in ("SECRET_KEY", "DATABASE_URL", "REDIS_URL", "SENTRY_DSN",
                 "CEREBRUM_MASTER_KEY", "DATA_ENCRYPTION_KEY",
                 "GDRIVE_SERVICE_ACCOUNT_JSON"):
        assert is_secret_env_name(name) is True, name
    for name in ("CEREBRUM_API_KEY_X", "GITHUB_TOKEN", "RENDER_API_KEY",
                 "R2_ACCESS_KEY_ID", "app_password", "my_PRIVATE_KEY",
                 "SERVICE_ACCOUNT_JSON", "SIGNING_KEY"):
        assert is_secret_env_name(name) is True, name
    # Case-insensitive.
    assert is_secret_env_name("secret_key") is True


def test_functional_system_env_survives():
    for name in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "TESSDATA_PREFIX",
                 "PYTHONPATH", "PYTHONIOENCODING", "NODE_OPTIONS",
                 "QT_QPA_PLATFORM", "LD_LIBRARY_PATH"):
        assert is_secret_env_name(name) is False, name


def test_scrubbed_env_removes_secrets_and_keeps_functional(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "sk")
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@h/db")
    monkeypatch.setenv("MY_APP_API_KEY", "k")
    monkeypatch.setenv("PATH", "C:\\keep")
    env = scrubbed_env()
    assert "SECRET_KEY" not in env
    assert "DATABASE_URL" not in env
    assert "MY_APP_API_KEY" not in env
    assert env["PATH"] == "C:\\keep"
    # The original environment is never mutated.
    assert "SECRET_KEY" in os.environ


def test_extra_functional_override_wins(monkeypatch):
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "0")
    env = scrubbed_env({"PYTHONDONTWRITEBYTECODE": "1"})
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"


def test_scrub_action_reports_removed_names(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "sk")
    monkeypatch.setenv("CEREBRUM_API_KEY", "k")
    monkeypatch.setenv("PATH", "C:\\keep")
    b = SubprocessEnvGuardBlock()
    r = _run(b.process({"action": "scrub", "extra": {"PYTHONDONTWRITEBYTECODE": "1"}}))
    assert r["status"] == "ok"
    assert "SECRET_KEY" in r["result"]["removed_secret_names"]
    assert "CEREBRUM_API_KEY" in r["result"]["removed_secret_names"]
    assert r["result"]["env"]["PATH"] == "C:\\keep"
    assert r["result"]["env"]["PYTHONDONTWRITEBYTECODE"] == "1"


def test_extra_reinjecting_a_secret_is_refused(monkeypatch):
    b = SubprocessEnvGuardBlock()
    r = _run(b.process({"action": "scrub", "extra": {"SECRET_KEY": "x"}}))
    assert r["status"] == "refused"
    assert "SECRET_KEY" in r["error"]
    r2 = _run(b.process({"action": "scrub", "extra": {"NEW_API_KEY": "x"}}))
    assert r2["status"] == "refused"


def test_scrub_with_non_mapping_extra_is_refused():
    b = SubprocessEnvGuardBlock()
    r = _run(b.process({"action": "scrub", "extra": "PATH=1"}))
    assert r["status"] == "refused"


def test_classify_without_name_is_refused():
    b = SubprocessEnvGuardBlock()
    assert _run(b.process({"action": "classify"}))["status"] == "refused"
    assert _run(b.process({"action": "classify", "name": "   "}))["status"] == "refused"
    r = _run(b.process({"action": "classify", "name": "AWS_ACCESS_TOKEN"}))
    assert r["result"] == {"name": "AWS_ACCESS_TOKEN", "secret": True}
    r2 = _run(b.process({"action": "classify", "name": "PATH"}))
    assert r2["result"]["secret"] is False


def test_audit_splits_secret_from_clean():
    b = SubprocessEnvGuardBlock()
    r = _run(b.process({"action": "audit", "names": ["PATH", "DB_TOKEN", "HOME"]}))
    assert r["status"] == "ok"
    assert r["result"]["secret"] == ["DB_TOKEN"]
    assert set(r["result"]["clean"]) == {"PATH", "HOME"}
    assert _run(b.process({"action": "audit", "names": []}))["status"] == "refused"


def test_unknown_action_is_error():
    b = SubprocessEnvGuardBlock()
    r = _run(b.process({"action": "nonsense"}))
    assert r["status"] == "error"
    assert r["block_id"] == "subprocess_env_guard"
