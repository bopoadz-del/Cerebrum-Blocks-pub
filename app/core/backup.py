"""Consistent snapshots of DATA_DIR, and the restore path.

Everything durable this service owns lives on one 1 GB Render disk at
``DATA_DIR``: the rate-limit/usage database, uploaded documents, captures,
publisher registrations, block certifications, the learning-engine store.
Losing the disk loses all of it; until now there was no copy anywhere.

SQLite files are snapshotted with the online backup API — a plain file copy
of a live WAL-mode database can capture a torn page and produce an archive
that restores without error and is quietly corrupt, the worst failure mode a
backup can have. Every snapshot is integrity-checked before it is archived.
Everything else is copied as files.

**Destination matters.** Archives default to ``DATA_DIR/backups`` — the same
disk. That protects against logical loss (accidental delete, a bad prune, a
misbehaving block), not against losing the disk itself. Point ``BACKUP_DIR``
somewhere else if disk loss is in scope.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import tarfile
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_KEEP = 14
ARCHIVE_PREFIX = "cerebrum-blocks-backup-"

# Never captured: the backup destination itself, and SQLite side files whose
# content is already folded into the online snapshot of their main database.
_EXCLUDED_DIRS = {"backups"}
_EXCLUDED_SUFFIXES = {".db-wal", ".db-shm"}


def _utcstamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def data_root() -> Path:
    return Path(os.getenv("DATA_DIR", "./data"))


def backup_root() -> Path:
    override = os.getenv("BACKUP_DIR", "").strip()
    if override:
        return Path(override)
    return data_root() / "backups"


@dataclass
class BackupResult:
    ok: bool
    archive: Optional[Path] = None
    bytes_written: int = 0
    included: List[str] = field(default_factory=list)
    skipped: Dict[str, str] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "archive": str(self.archive) if self.archive else None,
            "bytes_written": self.bytes_written,
            "included": list(self.included),
            "skipped": dict(self.skipped),
            "error": self.error,
        }


def snapshot_sqlite(source: Path, dest: Path) -> None:
    """Copy a live SQLite database consistently via the online backup API.

    The source is opened read-write on purpose: the backup API must read
    the live -wal when the database is in WAL mode, and a read-only
    connection to a WAL database fails (sqlite reports a spurious
    'disk I/O error'). The API itself only reads pages.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    src_conn = sqlite3.connect(str(source), timeout=5)
    try:
        mode = src_conn.execute("PRAGMA journal_mode").fetchone()[0]
        if str(mode).lower() == "wal":
            # Fold the WAL into the database before snapshotting: the
            # online backup API reading a live -wal fails on some
            # filesystems (CI runners report 'disk I/O error'). A
            # truncated WAL means the backup reads database pages only.
            src_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        dst_conn = sqlite3.connect(str(dest), timeout=5)
        try:
            src_conn.backup(dst_conn)
            # The online backup copies the source's WAL-mode header; the
            # snapshot then writes -wal/-shm side files of its own. Switching
            # it to DELETE mode checkpoints and removes them, so the archive
            # carries exactly one consistent .db file.
            dst_conn.execute("PRAGMA journal_mode=DELETE")
            dst_conn.commit()
        finally:
            dst_conn.close()
    finally:
        src_conn.close()


def verify_sqlite_snapshot(path: Path) -> Dict[str, int]:
    """Integrity-check a snapshot and count rows per table.

    The difference between "a file was produced" and "a database was
    produced". Runs on every backup, so an unopenable snapshot fails the job
    instead of sitting on disk looking like protection.
    """
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise RuntimeError(f"snapshot failed integrity check: {integrity}")
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ]
        return {
            t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            for t in tables
        }
    finally:
        conn.close()


def _is_excluded(entry: Path) -> bool:
    if entry.name in _EXCLUDED_DIRS:
        return True
    return any(entry.name.endswith(sfx) for sfx in _EXCLUDED_SUFFIXES)


def create_backup(*, dest_root: Optional[Path] = None) -> BackupResult:
    """Produce one timestamped archive of everything under DATA_DIR."""
    dest_root = Path(dest_root) if dest_root else backup_root()
    result = BackupResult(ok=False)

    root = data_root()
    if not root.is_dir():
        result.error = f"DATA_DIR does not exist: {root}"
        return result
    dest_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as staging_str:
        staging = Path(staging_str)
        manifest: List[str] = []

        for entry in sorted(root.iterdir()):
            if _is_excluded(entry):
                result.skipped[entry.name] = "excluded"
                continue
            try:
                if entry.is_file() and entry.suffix == ".db":
                    snapshot_sqlite(entry, staging / entry.name)
                    counts = verify_sqlite_snapshot(staging / entry.name)
                    manifest.extend(
                        f"{entry.name}:{t}={n}" for t, n in sorted(counts.items())
                    )
                elif entry.is_dir():
                    shutil.copytree(entry, staging / entry.name, dirs_exist_ok=True)
                elif entry.is_file():
                    shutil.copy2(entry, staging / entry.name)
                else:
                    result.skipped[entry.name] = "not a file or directory"
                    continue
                result.included.append(entry.name)
            except Exception as exc:  # noqa: BLE001
                # A database that cannot be snapshotted consistently fails the
                # whole job — an archive silently missing the usage DB would
                # look like protection and not be it.
                result.error = f"could not capture {entry.name}: {exc}"
                return result

        if manifest:
            (staging / "MANIFEST.txt").write_text(
                "\n".join(manifest), encoding="utf-8"
            )

        archive = dest_root / f"{ARCHIVE_PREFIX}{_utcstamp()}.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            for child in sorted(staging.iterdir()):
                tar.add(child, arcname=child.name)

        result.archive = archive
        result.bytes_written = archive.stat().st_size
        result.ok = True

    return result


def restore_backup(archive: Path, target_root: Path) -> Dict[str, Any]:
    """Unpack into an explicit ``target_root`` and verify any databases.

    Never restores over the live location: testing a restore must not be able
    to destroy production. Promoting a verified restore is a separate act.
    """
    archive = Path(archive)
    target_root = Path(target_root)
    target_root.mkdir(parents=True, exist_ok=True)

    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            name = member.name
            if name.startswith("/") or ".." in Path(name).parts:
                raise RuntimeError(f"refusing unsafe archive member: {name}")
            if member.issym() or member.islnk():
                # The name check above cannot see where a link POINTS. A
                # symlink member named "ok.db" targeting /etc/passwd passes
                # every path test and then writes outside target_root.
                raise RuntimeError(f"refusing link archive member: {name}")
        # PEP 706 filter: refuses absolute paths, parent traversal, links and
        # device nodes in the library, independently of the loop above.
        tar.extractall(target_root, filter="data")

    verified: Dict[str, Dict[str, int]] = {}
    for db in target_root.glob("*.db"):
        verified[db.name] = verify_sqlite_snapshot(db)
    return {"ok": True, "target": str(target_root), "verified": verified}


def prune_backups(dest_root: Optional[Path] = None, keep: int = DEFAULT_KEEP) -> List[Path]:
    """Delete all but the newest ``keep`` archives. Returns what was removed."""
    dest_root = Path(dest_root) if dest_root else backup_root()
    if not dest_root.is_dir():
        return []
    archives = sorted(
        (p for p in dest_root.glob(f"{ARCHIVE_PREFIX}*.tar.gz") if p.is_file()),
        key=lambda p: p.name,
        reverse=True,
    )
    removed: List[Path] = []
    for stale in archives[keep:]:
        stale.unlink()
        removed.append(stale)
    return removed
