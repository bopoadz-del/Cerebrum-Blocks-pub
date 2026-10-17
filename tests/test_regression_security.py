"""Regression tests for the security audit fixes (commits 2ca14353,
31638898). Each test names the audit issue tag (C1, C2, etc.).

Covers:
  - Tier × block allowlist (`enforce_block_access`)
  - /mcp ASGI auth wrapper (`asgi_auth_required`)
  - APIKeyAuth: role/tier population, constant-time compare, dev-env check
  - Rate-limit SQLite store
  - capture_id form-field validation
  - local_drive sandbox (DATA_DIR-scoped: jails absolute paths, refuses
    traversal, and confines writes)
  - Drive query injection guards
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import List, Tuple

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials


# ── Tier × block allowlist (C2-C11, I7-I8) ───────────────────────────────


def test_restricted_blocks_default_set_covers_audit_findings():
    from app.core.security import RESTRICTED_BLOCKS
    expected = {
        "code", "sandbox", "formula_executor",  # RCE primitives
        "secrets", "database",                   # vault / SQL
        "web", "webhook",                        # SSRF
        "file_hasher", "storage",                # FS
        "email", "billing",                      # privilege / state mutation
    }
    assert expected.issubset(RESTRICTED_BLOCKS)


def test_enforce_block_access_denies_standard_tier():
    from app.core.security import enforce_block_access
    auth = {"tier": "standard", "user": "spa", "role": "user"}
    with pytest.raises(HTTPException) as ei:
        enforce_block_access("code", auth)
    assert ei.value.status_code == 403
    assert "restricted" in str(ei.value.detail).lower()


def test_enforce_block_access_allows_unlimited_tier():
    from app.core.security import enforce_block_access
    auth = {"tier": "unlimited", "user": "master", "role": "admin"}
    enforce_block_access("code", auth)  # must not raise


def test_enforce_block_access_passes_through_non_restricted():
    from app.core.security import enforce_block_access
    auth = {"tier": "standard", "user": "spa", "role": "user"}
    enforce_block_access("chat", auth)
    enforce_block_access("pdf", auth)


def test_enforce_block_access_handles_missing_tier_field():
    """Defensive: an auth dict without a tier is rejected on restricted."""
    from app.core.security import enforce_block_access
    with pytest.raises(HTTPException):
        enforce_block_access("secrets", {"user": "?"})


# ── /mcp asgi_auth_required (C1) ─────────────────────────────────────────


def _capture_response(send_calls: List[dict]):
    async def send(message):
        send_calls.append(message)
    return send


def _build_scope(headers: List[Tuple[bytes, bytes]]):
    return {"type": "http", "headers": headers, "method": "GET", "path": "/mcp/sse"}


@pytest.mark.asyncio
async def test_mcp_auth_rejects_no_bearer():
    from app.core.security import asgi_auth_required
    inner_called = False

    async def inner(scope, receive, send):
        nonlocal inner_called
        inner_called = True

    wrapped = asgi_auth_required(inner)
    sent: List[dict] = []
    await wrapped(_build_scope([]), lambda: None, _capture_response(sent))
    assert inner_called is False
    assert sent[0]["status"] == 401


@pytest.mark.asyncio
async def test_mcp_auth_rejects_bogus_bearer():
    from app.core.security import asgi_auth_required
    wrapped = asgi_auth_required(lambda *a, **k: None)
    sent: List[dict] = []
    await wrapped(
        _build_scope([(b"authorization", b"Bearer not_a_real_key")]),
        lambda: None,
        _capture_response(sent),
    )
    assert sent[0]["status"] == 401


@pytest.mark.asyncio
async def test_mcp_auth_rejects_standard_tier(monkeypatch):
    """Audit C1: even a valid standard-tier key should not reach /mcp.
    The wrapper's default required_tier is 'unlimited'."""
    monkeypatch.setenv("CEREBRUM_API_KEY_TEST", "cb_std_xyz_999")
    monkeypatch.delenv("CEREBRUM_MCP_DISABLE_AUTH", raising=False)

    # Force a fresh APIKeyAuth instance so the env var lands in _keys
    from app.core import auth as auth_mod
    auth_mod.auth = auth_mod.APIKeyAuth()

    from app.core.security import asgi_auth_required
    wrapped = asgi_auth_required(lambda *a, **k: None)
    sent: List[dict] = []
    await wrapped(
        _build_scope([(b"authorization", b"Bearer cb_std_xyz_999")]),
        lambda: None,
        _capture_response(sent),
    )
    assert sent[0]["status"] == 403


@pytest.mark.asyncio
async def test_mcp_auth_allows_unlimited_tier(monkeypatch):
    monkeypatch.setenv("CEREBRUM_MASTER_KEY", "cb_master_zzz_777")
    monkeypatch.delenv("CEREBRUM_MCP_DISABLE_AUTH", raising=False)

    from app.core import auth as auth_mod
    auth_mod.auth = auth_mod.APIKeyAuth()

    from app.core.security import asgi_auth_required
    inner_called = False

    async def inner(scope, receive, send):
        nonlocal inner_called
        inner_called = True
        # Mimic SSE: send a dummy 200 so the test verifies the wrapper
        # passed control through.
        await send({"type": "http.response.start", "status": 200, "headers": []})

    wrapped = asgi_auth_required(inner)
    sent: List[dict] = []
    await wrapped(
        _build_scope([(b"authorization", b"Bearer cb_master_zzz_777")]),
        lambda: None,
        _capture_response(sent),
    )
    assert inner_called is True


# ── APIKeyAuth role / tier / dev-env (I1, M8) ────────────────────────────


@pytest.fixture
def fresh_auth(monkeypatch, tmp_path):
    """Reload APIKeyAuth in a clean env so tests don't bleed into each
    other. DATA_DIR points to a tmpdir so the SQLite rate-limit store
    is per-test."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    # Strip any leaked CEREBRUM_API_KEY_* / CEREBRUM_MASTER_KEY from prior tests.
    for k in list(os.environ):
        if k.startswith("CEREBRUM_API_KEY_") or k == "CEREBRUM_MASTER_KEY":
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ENV", "test")
    from app.core.auth import APIKeyAuth
    return APIKeyAuth()


def test_master_key_gets_admin_role(monkeypatch, fresh_auth):
    monkeypatch.setenv("CEREBRUM_MASTER_KEY", "cb_master_aaa")
    fresh_auth._reload_keys()
    data = fresh_auth.validate_key(
        HTTPAuthorizationCredentials(scheme="Bearer", credentials="cb_master_aaa"),
    )
    assert data["tier"] == "unlimited"
    assert data["role"] == "admin"


def test_standard_key_gets_user_role(monkeypatch, fresh_auth):
    monkeypatch.setenv("CEREBRUM_API_KEY_USER", "cb_std_bbb")
    fresh_auth._reload_keys()
    data = fresh_auth.validate_key(
        HTTPAuthorizationCredentials(scheme="Bearer", credentials="cb_std_bbb"),
    )
    assert data["tier"] == "standard"
    assert data["role"] == "user"


def test_invalid_key_raises_401(fresh_auth):
    with pytest.raises(HTTPException) as ei:
        fresh_auth.validate_key(
            HTTPAuthorizationCredentials(scheme="Bearer", credentials="not_a_real_key"),
        )
    assert ei.value.status_code == 401


def test_no_credentials_raises_401(fresh_auth):
    with pytest.raises(HTTPException) as ei:
        fresh_auth.validate_key(None)
    assert ei.value.status_code == 401


def test_dev_env_check_ignores_pytest_in_sys_modules(monkeypatch):
    """Audit M8: prior version returned True if pytest was loaded — that
    silently activated cb_dev_key in production whenever a worker had
    pytest preloaded for any reason."""
    from app.core.auth import APIKeyAuth
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("ENVIRONMENT", "production")
    # pytest IS in sys.modules when this test runs. The fix means dev
    # env should still report False.
    assert "pytest" in sys.modules
    assert APIKeyAuth._is_dev_environment() is False


# ── _UsageStore SQLite-backed rate limit (I3) ────────────────────────────


def test_usage_store_increments_atomically(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.core.auth import _UsageStore
    s = _UsageStore()
    hb = 12345
    assert s.increment("k", hb) == 1
    assert s.increment("k", hb) == 2
    assert s.increment("k", hb) == 3
    assert s.get("k", hb) == 3


def test_usage_store_isolates_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.core.auth import _UsageStore
    s = _UsageStore()
    hb = 99
    s.increment("alpha", hb)
    s.increment("alpha", hb)
    s.increment("beta", hb)
    assert s.get("alpha", hb) == 2
    assert s.get("beta", hb) == 1


def test_usage_store_prune_drops_old_buckets(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.core.auth import _UsageStore
    s = _UsageStore()
    s.increment("k", 100)
    s.increment("k", 101)
    s.prune_older_than(101)
    assert s.get("k", 100) == 0
    assert s.get("k", 101) == 1


def test_usage_store_falls_back_to_memory_when_db_unavailable(tmp_path, monkeypatch):
    """If DATA_DIR is read-only or unreachable, the store should not
    raise — it should log a warning and use the in-memory fallback."""
    # Use an existing file as DATA_DIR so directory creation fails on all
    # platforms, forcing the SQLite fallback path.
    bad_data_dir = tmp_path / "not_a_dir"
    bad_data_dir.write_text("x")
    monkeypatch.setenv("DATA_DIR", str(bad_data_dir))
    from app.core.auth import _UsageStore

    s = _UsageStore()
    # Either DB happened to work, or it gave up and dropped to memory —
    # either way, increment must still work.
    assert s.increment("k", 1) == 1
    assert s.get("k", 1) == 1


# ── capture_id traversal guard (C12) ─────────────────────────────────────


def test_capture_id_regex_accepts_uuid_short():
    from app.routers.capture import _CAPTURE_ID_RE
    assert _CAPTURE_ID_RE.match("a1b2c3d4")
    assert _CAPTURE_ID_RE.match("user_session-99")
    assert _CAPTURE_ID_RE.match("X" * 32)


def test_capture_id_regex_rejects_traversal_attempts():
    from app.routers.capture import _CAPTURE_ID_RE
    assert not _CAPTURE_ID_RE.match("../../tmp/x")
    assert not _CAPTURE_ID_RE.match("a/b/c")
    assert not _CAPTURE_ID_RE.match("foo bar")
    assert not _CAPTURE_ID_RE.match("foo;rm -rf")
    assert not _CAPTURE_ID_RE.match("X" * 33)
    assert not _CAPTURE_ID_RE.match("")


# ── local_drive sandbox (prior C1) ───────────────────────────────────────


@pytest.mark.asyncio
async def test_local_drive_cannot_reach_outside_its_root(tmp_path, monkeypatch):
    """Audit C1. The property is containment, not a particular error string.

    The block jails rather than rejects: a leading slash is stripped, so
    "/etc" resolves to <root>/etc. That is safe, and asserting on the words
    "outside"/"permitted" (as this test used to) only checked the wording of
    a message. What must be true is that no request reaches a real path
    outside the root -- so that is what is asserted, by every route in.
    """
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("LOCAL_DRIVE_ROOT", raising=False)
    from app.blocks.local_drive import LocalDriveBlock
    b = LocalDriveBlock()

    # 1. An absolute path is jailed, never followed to the real filesystem.
    listed = await b.process("/etc", {"operation": "list"})
    names = [f["name"] for f in listed.get("files", [])]
    assert "passwd" not in names, f"listed the real /etc: {listed}"

    # 2. Reading a real system file gets nothing back.
    read = await b.process(None, {"operation": "read", "file_path": "/etc/passwd"})
    assert read["status"] == "error", f"read the real /etc/passwd: {read}"
    assert "root:" not in str(read)

    # 3. Traversal is refused outright -- this one the realpath check owns.
    # POSIX separators only: on Linux a backslash is an ordinary filename
    # character, so "..\..\etc" is not a traversal there at all -- asserting
    # it were would be asserting the platform, not the block.
    for escape in ("../", "../../etc", "a/../../.."):
        out = await b.process(escape, {"operation": "list"})
        assert out["status"] == "error", f"{escape!r} was not refused: {out}"
        assert "escapes" in out.get("error", "").lower(), out

    # 4. A symlink pointing out is refused too. realpath resolves it before
    #    the prefix check, which is the reason that check uses realpath.
    outside = tmp_path.parent / "outside_the_root"
    outside.mkdir(exist_ok=True)
    (outside / "secret.txt").write_text("do not read me", encoding="utf-8")
    link = tmp_path / "escape_link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pass  # unprivileged Windows cannot create one; the other routes stand
    else:
        via_link = await b.process("escape_link", {"operation": "list"})
        assert via_link["status"] == "error", f"followed a symlink out: {via_link}"


@pytest.mark.asyncio
async def test_local_drive_writes_only_inside_its_root(tmp_path, monkeypatch):
    """The old test asserted writes were "not supported". They are -- the
    block is declared as "list, read, write files" and generated platforms
    use it. Asserting the opposite made this a check on a design that had
    already changed; the property that still matters is that a write cannot
    land outside the root.
    """
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("LOCAL_DRIVE_ROOT", raising=False)
    from app.blocks.local_drive import LocalDriveBlock
    b = LocalDriveBlock()

    # An absolute target is jailed into the root, not written to the real path.
    victim = Path("/tmp/cerebrum_local_drive_escape_probe.txt")
    if victim.exists():
        victim.unlink()
    res = await b.process(
        None,
        {"operation": "write",
         "file_path": "/tmp/cerebrum_local_drive_escape_probe.txt",
         "content": "x"},
    )
    assert res["status"] == "success", res
    assert not victim.exists(), "the write escaped to the real /tmp"
    assert (tmp_path / "tmp" / "cerebrum_local_drive_escape_probe.txt").is_file(), (
        "the write did not land inside the root either -- it went nowhere"
    )

    # Traversal is refused rather than jailed.
    escaped = await b.process(
        None, {"operation": "write", "file_path": "../escaped.txt", "content": "x"}
    )
    assert escaped["status"] == "error", escaped
    assert "escapes" in escaped.get("error", "").lower(), escaped
    assert not (tmp_path.parent / "escaped.txt").exists()


@pytest.mark.asyncio
async def test_local_drive_lists_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    (tmp_path / "a.txt").write_text("hi")
    (tmp_path / "subdir").mkdir()
    from app.blocks.local_drive import LocalDriveBlock
    b = LocalDriveBlock()
    res = await b.process(".", {"operation": "list"})
    assert res["status"] == "success"
    names = [f["name"] for f in res["files"]]
    assert "a.txt" in names
    assert "subdir" in names


# ── Drive query injection (I5) ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_google_drive_rejects_quote_in_query(monkeypatch):
    """Audit I5: query containing single-quote is rejected before hitting
    the Drive Query Language. Bypassing the OAuth-not-configured branch
    via a monkeypatched access-token fetcher so the check actually runs."""
    from app.blocks import google_drive as gd

    async def fake_token():
        return "fake_access_token"

    monkeypatch.setattr(gd, "_get_access_token", fake_token)
    b = gd.GoogleDriveBlock()
    res = await b.process("' OR trashed=false OR '", {"operation": "list"})
    assert res["status"] == "error"
    assert "single quote" in res.get("error", "").lower()


@pytest.mark.asyncio
async def test_google_drive_rejects_quote_in_folder_id(monkeypatch):
    """The second interpolation site. ``'{folder_id}' in parents`` is the same
    literal-delimited construction as the name filter, so a guard on the
    search box alone would leave the door open one parameter along."""
    from app.blocks import google_drive as gd

    async def fake_token():
        return "fake_access_token"

    monkeypatch.setattr(gd, "_get_access_token", fake_token)
    b = gd.GoogleDriveBlock()
    res = await b.process("", {"operation": "list", "folder_id": "x' or trashed=false or '"})
    assert res["status"] == "error"
    assert "single quote" in res.get("error", "").lower(), res


@pytest.mark.asyncio
async def test_onedrive_rejects_quote_in_query(monkeypatch):
    from app.blocks import onedrive as od

    async def fake_token():
        return "fake_access_token"

    monkeypatch.setattr(od, "_get_access_token", fake_token)
    b = od.OneDriveBlock()
    res = await b.process("' OR contains(path,'/' OR '", {"operation": "list"})
    assert res["status"] == "error"
    assert "single quote" in res.get("error", "").lower()


def test_onedrive_scope_is_read_only():
    """Audit I6: scope must be Files.Read only — not Files.ReadWrite."""
    from app.blocks.onedrive import _SCOPES
    assert "Files.ReadWrite" not in _SCOPES
    assert "Files.Read" in _SCOPES
