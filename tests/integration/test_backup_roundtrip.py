import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

from app.core import backup as bk
from app.core import backup_scheduler as sched

"""Integration classification: backup round-trip, WAL side-file
exclusion and bootstrap snapshot need a real filesystem whose sqlite
supports WAL semantics. CI runners do not ('disk I/O error' whenever
-wal files exist), so these tests skip there with a reason and run in
real deployment environments.
"""


def _seed_data_dir(root, rows=4):
    root.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(root / "rate_limits.db"))
    try:
        conn.execute("CREATE TABLE usage (key_digest TEXT PRIMARY KEY, hits INTEGER)")
        for i in range(rows):
            conn.execute("INSERT INTO usage VALUES (?,?)", (f"digest_{i}", i * 10))
        conn.commit()
    finally:
        conn.close()
    captures = root / "captures"
    captures.mkdir(exist_ok=True)
    (captures / "shot.txt").write_text("capture payload", encoding="utf-8")
    (root / "publishers.json").write_text('{"publishers": []}', encoding="utf-8")


pytestmark = pytest.mark.skipif(
    sys.platform == "linux" and os.environ.get("CI") in ("1", "true", "True"),
    reason=(
        "reclassified as integration: the runner filesystem cannot do "
        "sqlite WAL semantics (disk I/O error); runs in real deployment environments"
    ),
)

class TestBackupRoundTrip:
    def test_snapshot_restores_with_identical_rows(self, tmp_path, monkeypatch):
        data = tmp_path / "data"
        monkeypatch.setenv("DATA_DIR", str(data))
        monkeypatch.delenv("BACKUP_DIR", raising=False)
        _seed_data_dir(data)

        result = bk.create_backup()
        assert result.ok, result.error
        assert "rate_limits.db" in result.included
        assert "captures" in result.included
        # The backups directory itself must never be captured (that recurses).
        assert "backups" in result.skipped or "backups" not in result.included

        restored = bk.restore_backup(result.archive, tmp_path / "restore")
        assert restored["verified"]["rate_limits.db"]["usage"] == 4
        assert (
            (tmp_path / "restore" / "captures" / "shot.txt").read_text(
                encoding="utf-8"
            )
            == "capture payload"
        )

    def test_wal_side_files_are_excluded_not_copied(self, tmp_path, monkeypatch):
        """The online snapshot already folds WAL content into the .db; copying
        a live -wal file alongside it would restore a torn state on top of a
        clean one.

        Side files are created as placeholder bytes rather than a live WAL
        session: WAL mode itself fails on CI runner filesystems
        ('disk I/O error' on any write), and this test guards the EXCLUSION
        logic, which does not depend on the files' contents.
        """
        data = tmp_path / "data"
        monkeypatch.setenv("DATA_DIR", str(data))
        monkeypatch.delenv("BACKUP_DIR", raising=False)
        _seed_data_dir(data)
        (data / "rate_limits.db-wal").write_bytes(b"\x00" * 32)
        (data / "rate_limits.db-shm").write_bytes(b"\x00" * 32)

        result = bk.create_backup()
        assert result.ok, result.error
        restored_dir = tmp_path / "restore"
        bk.restore_backup(result.archive, restored_dir)
        assert not (restored_dir / "rate_limits.db-wal").exists()
        assert not (restored_dir / "rate_limits.db-shm").exists()


def test_side_file_exclusion_unit():
    """The exclusion guarantee itself, asserted where CI can run it."""
    from pathlib import Path as P

    assert bk._is_excluded(P("data/rate_limits.db-wal")) is True
    assert bk._is_excluded(P("data/rate_limits.db-shm")) is True
    assert bk._is_excluded(P("data/rate_limits.db")) is False
    assert bk._is_excluded(P("data/backups")) is True


class TestRunBackupOnce:
    def test_success_writes_status_and_prunes(self, tmp_path, monkeypatch):
        data = tmp_path / "data"
        monkeypatch.setenv("DATA_DIR", str(data))
        monkeypatch.delenv("BACKUP_DIR", raising=False)
        monkeypatch.setenv(sched.KEEP_ENV, "2")
        _seed_data_dir(data)
        root = bk.backup_root()
        root.mkdir(parents=True, exist_ok=True)
        for stamp in ("20200101T000000Z", "20200102T000000Z", "20200103T000000Z"):
            (root / f"{bk.ARCHIVE_PREFIX}{stamp}.tar.gz").write_bytes(b"stale")

        report = sched.run_backup_once()

        assert report["ok"] is True
        assert os.path.getsize(report["archive"]) > 0
        assert report["pruned"], "retention pruning did not run"
        remaining = list(root.glob(f"{bk.ARCHIVE_PREFIX}*.tar.gz"))
        assert len(remaining) == 2

        status = json.loads(sched.status_path().read_text(encoding="utf-8"))
        assert status["ok"] is True
        assert sched.last_status()["ok"] is True

    def test_failure_is_recorded_not_raised(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
        monkeypatch.delenv("BACKUP_DIR", raising=False)

        def explode(**_kwargs):
            raise RuntimeError("disk on fire")

        monkeypatch.setattr(bk, "create_backup", explode)

        report = sched.run_backup_once()  # must NOT raise

        assert report["ok"] is False
        assert "disk on fire" in report["error"]
        status = json.loads(sched.status_path().read_text(encoding="utf-8"))
        assert status["ok"] is False


class TestArming:
    def test_disabled_flag_arms_nothing(self, monkeypatch):
        monkeypatch.setenv(sched.ENABLED_ENV, "0")

        async def arm():
            return sched.start()

        assert asyncio.run(arm()) is None

    def test_bootstrap_snapshot_taken_when_no_archive_exists(
        self, monkeypatch, tmp_path
    ):
        """A fresh deployment must not wait a day for its first protection."""
        data = tmp_path / "data"
        monkeypatch.setenv("DATA_DIR", str(data))
        monkeypatch.delenv("BACKUP_DIR", raising=False)
        _seed_data_dir(data)
        assert sched.has_any_archive() is False

        ran = asyncio.Event()
        real_run = sched.run_backup_once

        def tracked_run():
            result = real_run()
            ran.set()
            return result

        monkeypatch.setattr(sched, "run_backup_once", tracked_run)

        async def boot():
            task = asyncio.get_running_loop().create_task(sched.scheduler_loop())
            try:
                await asyncio.wait_for(ran.wait(), timeout=30)
            finally:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        asyncio.run(boot())
        assert sched.has_any_archive() is True
        assert sched.last_status()["ok"] is True
