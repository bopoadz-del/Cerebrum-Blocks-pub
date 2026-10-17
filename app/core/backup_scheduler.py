"""Nightly backup scheduling, run inside the web service process.

Why in-process and not a Render cron job: Render cron jobs cannot mount
persistent disks, and a disk is accessible by exactly one service — nothing
outside this process can ever see ``DATA_DIR``. The web service runs
continuously on a paid plan, which makes an asyncio task a reliable vehicle.
(The same conclusion, reached the same day, as <private-repo>'s
``core/backup_scheduler.py`` — the platform constraint is identical.)

Env knobs:

* ``BACKUP_SCHEDULE_ENABLED`` — "1" (default) schedules nightly; "0" off.
* ``BACKUP_UTC_HOUR``         — hour of day, UTC, default 4 (offset from
  CerebrumDev's 03:00 so the two snapshots never contend for anything).
* ``BACKUP_KEEP``             — archives retained after pruning, default 14.

Every run — success or failure — writes ``last_backup.json`` next to the
archives; failures log at ERROR so Sentry's logging integration exports
them. The loop never raises: a crashed scheduler is a silent end to all
future backups. If no archive exists at startup, one is taken immediately —
a fresh deployment is unprotected until its first snapshot.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from . import backup

logger = logging.getLogger("cerebrum.backup")

ENABLED_ENV = "BACKUP_SCHEDULE_ENABLED"
HOUR_ENV = "BACKUP_UTC_HOUR"
KEEP_ENV = "BACKUP_KEEP"
DEFAULT_HOUR = 4

STATUS_FILENAME = "last_backup.json"


def scheduler_enabled() -> bool:
    return os.getenv(ENABLED_ENV, "1").strip().lower() not in {"0", "false", "no", "off"}


def scheduled_hour() -> int:
    raw = os.getenv(HOUR_ENV, "").strip()
    try:
        hour = int(raw) if raw else DEFAULT_HOUR
    except ValueError:
        logger.warning("ignoring non-numeric %s=%r", HOUR_ENV, raw)
        return DEFAULT_HOUR
    if not 0 <= hour <= 23:
        logger.warning("ignoring out-of-range %s=%r", HOUR_ENV, raw)
        return DEFAULT_HOUR
    return hour


def keep_count() -> int:
    raw = os.getenv(KEEP_ENV, "").strip()
    try:
        keep = int(raw) if raw else backup.DEFAULT_KEEP
    except ValueError:
        logger.warning("ignoring non-numeric %s=%r", KEEP_ENV, raw)
        return backup.DEFAULT_KEEP
    return keep if keep >= 1 else backup.DEFAULT_KEEP


def seconds_until_next_run(hour: int, now: Optional[datetime] = None) -> float:
    """Seconds until the next ``hour``:00 UTC; exactly-now means tomorrow.

    The loop calls this immediately after a run finishes — returning 0 at
    ``hour``:00:00 sharp would run the job twice back to back.
    """
    now = now or datetime.now(timezone.utc)
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def status_path() -> Path:
    return backup.backup_root() / STATUS_FILENAME


def last_status() -> Optional[Dict[str, Any]]:
    try:
        return json.loads(status_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def has_any_archive() -> bool:
    root = backup.backup_root()
    if not root.is_dir():
        return False
    return any(root.glob(f"{backup.ARCHIVE_PREFIX}*.tar.gz"))


def run_backup_once() -> Dict[str, Any]:
    """One backup + prune. Blocking; never raises — the report is the record."""
    started = datetime.now(timezone.utc).isoformat()
    try:
        result = backup.create_backup()
        report: Dict[str, Any] = {"at": started, **result.to_dict()}
        if result.ok:
            removed = backup.prune_backups(keep=keep_count())
            report["pruned"] = [p.name for p in removed]
    except Exception as exc:  # noqa: BLE001 — the loop must survive anything
        report = {"at": started, "ok": False, "error": f"{type(exc).__name__}: {exc}"}

    try:
        path = status_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.error("could not write backup status file: %s", exc)

    if report.get("ok"):
        logger.info(
            "nightly backup ok: %s (%d bytes, included=%s)",
            report.get("archive"),
            report.get("bytes_written", 0),
            report.get("included"),
        )
    else:
        # ERROR on purpose: Sentry's logging integration turns this into an
        # event — the only alerting channel an in-process job has.
        logger.error("nightly backup FAILED: %s", report.get("error"))
    return report


async def scheduler_loop() -> None:
    if not has_any_archive():
        logger.info("no existing backup archive — taking a bootstrap snapshot now")
        await asyncio.to_thread(run_backup_once)
    while True:
        delay = seconds_until_next_run(scheduled_hour())
        logger.info("backup scheduler: next run in %.0fs", delay)
        await asyncio.sleep(delay)
        await asyncio.to_thread(run_backup_once)


def start() -> Optional["asyncio.Task[None]"]:
    """Arm the scheduler. Returns the task, or None when disabled."""
    if not scheduler_enabled():
        logger.info("backup scheduler disabled via %s", ENABLED_ENV)
        return None
    return asyncio.get_running_loop().create_task(scheduler_loop(), name="nightly-backup")
