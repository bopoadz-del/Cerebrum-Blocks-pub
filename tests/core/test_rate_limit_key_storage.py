"""A raw API key must never be recoverable from the rate-limit database.

Shape: drive the store the way the request path drives it, then read the
SQLite files off disk as bytes and assert the credential is not in them.
Byte-level, not schema-level: a DELETE leaves the plaintext in freed pages
and in the write-ahead log, so an assertion phrased as "the table has no
plaintext rows" would pass while the secret is still sitting in the file.
"""

from __future__ import annotations

import os
import sqlite3
import time

import pytest

from app.core.auth import _UsageStore


MASTER_KEY = __import__("base64").urlsafe_b64encode(__import__("os").urandom(32)).decode().rstrip("=")
TENANT_KEY = "cb_tenant_TESTSENTINEL_0f9e8d7c6b5a43213456"


def _db_bytes(data_dir) -> bytes:
    """Every byte SQLite persisted: main database, WAL, and shared-memory."""
    blob = b""
    base = os.path.join(str(data_dir), "rate_limits.db")
    for path in (base, base + "-wal", base + "-shm"):
        if os.path.exists(path):
            with open(path, "rb") as fh:
                blob += fh.read()
    return blob


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    target = tmp_path / "data"
    target.mkdir()
    monkeypatch.setenv("DATA_DIR", str(target))
    return target


def test_raw_key_absent_from_database_bytes(data_dir):
    store = _UsageStore()
    assert store._db_path is not None, "expected the SQLite backend, not the fallback"
    bucket = int(time.time() / 3600)
    store.increment(MASTER_KEY, bucket)
    store.increment(TENANT_KEY, bucket)
    store.increment(TENANT_KEY, bucket)

    blob = _db_bytes(data_dir)
    assert blob, "expected the rate-limit database to exist on disk"
    assert MASTER_KEY.encode() not in blob
    assert TENANT_KEY.encode() not in blob


def test_rate_limiting_still_counts_per_key(data_dir):
    """Hashing must be behaviour-preserving: distinct keys, distinct counters."""
    store = _UsageStore()
    bucket = int(time.time() / 3600)
    assert store.increment(MASTER_KEY, bucket) == 1
    assert store.increment(MASTER_KEY, bucket) == 2
    assert store.increment(TENANT_KEY, bucket) == 1
    assert store.get(MASTER_KEY, bucket) == 2
    assert store.get(TENANT_KEY, bucket) == 1
    assert store.get("cb_never_seen_before_key", bucket) == 0


def test_counters_survive_a_restart(data_dir):
    """The cross-process guarantee the SQLite backend exists for."""
    bucket = int(time.time() / 3600)
    first = _UsageStore()
    first.increment(TENANT_KEY, bucket)
    first.increment(TENANT_KEY, bucket)
    second = _UsageStore()
    assert second.get(TENANT_KEY, bucket) == 2


def test_legacy_plaintext_database_is_purged_on_open(data_dir):
    """An existing pre-hash database must not crash the service, and must
    not leave the plaintext keys readable in the file afterwards."""
    path = os.path.join(str(data_dir), "rate_limits.db")
    bucket = int(time.time() / 3600)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS usage("
        "  key TEXT NOT NULL, hour_bucket INTEGER NOT NULL, "
        "  count INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (key, hour_bucket))"
    )
    conn.executemany(
        "INSERT INTO usage(key, hour_bucket, count) VALUES(?, ?, ?)",
        [(MASTER_KEY, bucket, 7), (TENANT_KEY, bucket, 3)],
    )
    conn.commit()
    conn.close()

    # Sanity: the fixture really did write the plaintext we are about to
    # demand is gone. Without this the test could pass vacuously.
    assert MASTER_KEY.encode() in _db_bytes(data_dir)

    store = _UsageStore()
    assert store._db_path is not None

    blob = _db_bytes(data_dir)
    assert MASTER_KEY.encode() not in blob
    assert TENANT_KEY.encode() not in blob

    # And the store is functional afterwards.
    assert store.increment(MASTER_KEY, bucket) == 1


def test_digest_is_not_reversible_and_is_stable(data_dir):
    store = _UsageStore()
    digest = store._digest(MASTER_KEY)
    assert digest != MASTER_KEY
    assert MASTER_KEY not in digest
    assert len(digest) == 64
    assert store._digest(MASTER_KEY) == digest
    assert store._digest(TENANT_KEY) != digest
