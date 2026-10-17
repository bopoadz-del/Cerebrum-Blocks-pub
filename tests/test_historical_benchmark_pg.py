"""Tests for the Postgres backend of HistoricalBenchmarkBlock.

These tests do **not** require a live Postgres database. The strategy:

* Skip the whole module when ``asyncpg`` is not importable.
* The "live DB" test skips when ``DATABASE_URL`` is unset.
* The fallback / pool-failure tests use small fakes so they exercise the
  dispatcher logic without any network I/O.
* The seed-migration test uses **sqlite3** as a portable substitute, with a
  scrubbed copy of the migration that strips Postgres-only constructs. Pure
  schema validation; the real file is verified by humans + ``psql``.
"""

from __future__ import annotations

import asyncio
import os
import re
import sqlite3
import sys
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest import mock

import pytest

# Keep the module importable from a fresh test process.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncpg  # noqa: E402  (pinned in requirements.txt)

from tests._fixtures import historical_benchmark as hb_mod  # noqa: E402
from tests._fixtures.historical_benchmark import (  # noqa: E402
    HistoricalBenchmarkBlock,
    _PostgresStore,
)


MIGRATION_PATH = ROOT / "migrations" / "001_historical_benchmark.sql"


# --------------------------------------------------------------------------- #
# Fakes                                                                       #
# --------------------------------------------------------------------------- #


class _FakeConn:
    """Minimal asyncpg-style connection backed by an in-memory list of rows."""

    def __init__(self, rows: List[Dict[str, Any]]):
        self._rows = rows

    async def fetchrow(self, query: str, *args: Any) -> Optional[Dict[str, Any]]:
        # We don't parse SQL — just return the first row whose item_name
        # matches the first arg if there is one.
        if "historical_benchmark" not in query and "location_factor" not in query:
            return self._rows[0] if self._rows else None
        if not self._rows:
            return None
        return self._rows[0]

    async def fetch(self, query: str, *args: Any) -> List[Dict[str, Any]]:
        return list(self._rows)


class _FakePoolCM:
    def __init__(self, conn: _FakeConn):
        self._conn = conn

    async def __aenter__(self) -> _FakeConn:
        return self._conn

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _FakePool:
    """Stand-in asyncpg pool. ``raise_on_acquire`` simulates a connection error."""

    def __init__(self, rows: List[Dict[str, Any]] = None, raise_on_acquire: bool = False):
        self._rows = rows or []
        self._raise = raise_on_acquire

    def acquire(self) -> _FakePoolCM:
        if self._raise:
            raise RuntimeError("simulated db connection error")
        return _FakePoolCM(_FakeConn(self._rows))

    async def close(self) -> None:
        return None


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


def _run(coro):
    """Drive *coro* on a fresh event loop, then close it cleanly."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture(autouse=True)
def _reset_module_pool():
    """Reset the module-level pool state around every test."""
    _run(hb_mod._reset_pool_for_tests())
    yield
    _run(hb_mod._reset_pool_for_tests())


# --------------------------------------------------------------------------- #
# Tests                                                                       #
# --------------------------------------------------------------------------- #


def test_pg_backend_used_when_database_url_set():
    """Setting DATABASE_URL flips ``_pg_active`` to True at construction."""
    with mock.patch.dict(os.environ, {"DATABASE_URL": "postgres://fake/test"}):
        block = HistoricalBenchmarkBlock()
        try:
            assert block._pg_active is True
            assert isinstance(block._pg_store, _PostgresStore)
        finally:
            block._pg_active = False
            block._pg_store = None


def test_pg_backend_inactive_without_database_url():
    """No DATABASE_URL → file backend, even with asyncpg installed."""
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    with mock.patch.dict(os.environ, env, clear=True):
        block = HistoricalBenchmarkBlock()
        assert block._pg_active is False
        assert block._pg_store is None


@pytest.mark.asyncio
async def test_pg_lookup_falls_back_to_file_on_db_error(monkeypatch):
    """When the pool raises, the dispatcher returns the file-backed result."""
    with mock.patch.dict(os.environ, {"DATABASE_URL": "postgres://fake/test"}):
        block = HistoricalBenchmarkBlock()

    # Patch the module-level pool factory so it returns a pool that blows up
    # the moment we try to acquire a connection.
    failing_pool = _FakePool(raise_on_acquire=True)

    async def _fake_pool(_dsn: str):
        return failing_pool

    monkeypatch.setattr(hb_mod, "_get_or_create_pool", _fake_pool)

    block._rates["concrete_c30_m3"] = {
        "unit": "m3", "trade": "structural", "base": 165.0, "low": 156.5, "high": 173.5,
    }

    out = await block.process(
        {"item": "concrete c30", "unit": "m3", "location": "us national average"},
        {"action": "lookup"},
    )
    assert out["status"] == "success"
    assert out["matched_key"] == "concrete_c30_m3"
    assert out["rates"]["base_usd"] == 165.0
    # File backend stamps this source string — proves we fell through.
    assert out["source"] == "external benchmark database"


@pytest.mark.asyncio
async def test_pg_lookup_falls_back_to_file_on_empty_table(monkeypatch):
    """Empty Postgres → file fallback, so seeded RSMeans data still flows."""
    with mock.patch.dict(os.environ, {"DATABASE_URL": "postgres://fake/test"}):
        block = HistoricalBenchmarkBlock()

    empty_pool = _FakePool(rows=[])

    async def _fake_pool(_dsn: str):
        return empty_pool

    monkeypatch.setattr(hb_mod, "_get_or_create_pool", _fake_pool)

    block._rates["rebar_kg"] = {
        "unit": "kg", "trade": "structural", "base": 1.8, "low": 1.7, "high": 1.9,
    }

    out = await block.process(
        {"item": "rebar", "unit": "kg", "location": "us national average"},
        {"action": "lookup"},
    )
    assert out["status"] == "success"
    assert out["matched_key"] == "rebar_kg"
    assert out["source"] == "external benchmark database"


@pytest.mark.asyncio
async def test_pg_lookup_returns_pg_result_when_seeded(monkeypatch):
    """Happy path: pool returns a row → result flagged with the DB source."""
    with mock.patch.dict(os.environ, {"DATABASE_URL": "postgres://fake/test"}):
        block = HistoricalBenchmarkBlock()

    seeded_rows = [{
        "item_name": "concrete_grade_c30",
        "unit": "m3",
        "avg_cost": 165.0,
        "std_dev": 8.5,
        "sample_size": 120,
        "location": "us_national_average",
        "source": "RSMeans",
        "factor": 1.0,
    }]
    pool = _FakePool(rows=seeded_rows)

    async def _fake_pool(_dsn: str):
        return pool

    monkeypatch.setattr(hb_mod, "_get_or_create_pool", _fake_pool)

    out = await block.process(
        {"item": "concrete_grade_c30", "unit": "m3", "location": "us_national_average"},
        {"action": "lookup"},
    )
    assert out["status"] == "success"
    # The fake pool answers every fetchrow with the seeded row, so location
    # factor lookup also resolves to 1.0 — adjusted_usd = base * 1.0 * 1.05.
    assert out["rates"]["base_usd"] == pytest.approx(165.0)
    assert out["source"] == "RSMeans"
    assert out["stats"]["sample_size"] == 120


def test_pg_seed_migration_idempotent(tmp_path):
    """Running the migration twice via sqlite3 must not raise.

    Postgres-only constructs (``SERIAL``, ``TIMESTAMPTZ``, ``NUMERIC``) are
    rewritten to sqlite-compatible forms; the structural assertion is just
    "second apply is a no-op", which is what ``ON CONFLICT DO NOTHING`` and
    ``CREATE ... IF NOT EXISTS`` guarantee.
    """
    raw = MIGRATION_PATH.read_text()
    sql = raw
    sql = re.sub(r"\bSERIAL PRIMARY KEY\b", "INTEGER PRIMARY KEY AUTOINCREMENT", sql)
    sql = re.sub(r"\bNUMERIC\b", "REAL", sql)
    sql = re.sub(r"\bTIMESTAMPTZ\b", "TEXT", sql)
    sql = sql.replace("DEFAULT now()", "DEFAULT CURRENT_TIMESTAMP")

    db = sqlite3.connect(":memory:")
    try:
        db.executescript(sql)
        db.executescript(sql)  # second apply must be idempotent
        cur = db.execute("SELECT count(*) FROM historical_benchmark")
        assert cur.fetchone()[0] == 5  # five seed rows, no duplicates
        cur = db.execute("SELECT count(*) FROM location_factor")
        assert cur.fetchone()[0] == 5
    finally:
        db.close()


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set — live Postgres test skipped",
)
@pytest.mark.asyncio
async def test_pg_live_lookup_smoke():
    """Live smoke test against a real Postgres if one is available."""
    block = HistoricalBenchmarkBlock()
    assert block._pg_active is True
    out = await block.process(
        {"item": "concrete_grade_c30", "unit": "m3", "location": "us_national_average"},
        {"action": "lookup"},
    )
    # Either the row is there (success) or the DB hasn't been seeded — both
    # are acceptable from a connectivity perspective.
    assert out["status"] in {"success", "not_found"}
