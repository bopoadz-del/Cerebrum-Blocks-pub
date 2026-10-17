"""Neutral append-only hash-chained audit evidence log."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List


class AuditIntegrityError(Exception):
    """Raised when an audit chain fails verification."""


ZERO_HASH = "0" * 64


def _canonical(record: Dict[str, Any]) -> str:
    """Stable JSON serialization for hashing."""
    return json.dumps(record, sort_keys=True, separators=(",", ":"))


def _hash(record: Dict[str, Any]) -> str:
    """SHA-256 hex digest of a canonical record."""
    return hashlib.sha256(_canonical(record).encode("utf-8")).hexdigest()


class AuditLog:
    """Append-only tamper-evident audit record chain."""

    def __init__(self) -> None:
        self._records: List[Dict[str, Any]] = []

    def record(
        self,
        event_type: str,
        principal: Dict[str, Any],
        scope: Dict[str, Any],
        action: str,
        outcome: str,
        payload: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Append an audit record and return it with hash evidence."""
        previous_hash = self._records[-1]["record_hash"] if self._records else ZERO_HASH
        entry: Dict[str, Any] = {
            "event_type": event_type,
            "principal": principal,
            "scope": scope,
            "action": action,
            "outcome": outcome,
            "payload": payload or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "previous_hash": previous_hash,
            "record_hash": "",  # populated after hashing
        }
        entry["record_hash"] = _hash(
            {k: v for k, v in entry.items() if k != "record_hash"}
        )
        self._records.append(entry)
        return entry

    def records(self) -> List[Dict[str, Any]]:
        return list(self._records)

    def reset(self) -> None:
        self._records.clear()

    @staticmethod
    def verify_chain(records: List[Dict[str, Any]]) -> bool:
        """Verify an audit chain; raise ``AuditIntegrityError`` on tampering."""
        previous_hash = ZERO_HASH
        for index, record in enumerate(records):
            # Verify linkage.
            if record.get("previous_hash") != previous_hash:
                raise AuditIntegrityError(
                    f"chain broken at index {index}: previous hash mismatch"
                )
            # Verify record hash integrity (recompute without the stored hash).
            recomputed = {k: v for k, v in record.items() if k != "record_hash"}
            if _hash(recomputed) != record.get("record_hash"):
                raise AuditIntegrityError(
                    f"record tampered at index {index}: hash mismatch"
                )
            previous_hash = record["record_hash"]
        return True


# Module-level default audit log.
_default_log = AuditLog()


def reset_audit_log() -> None:
    """Reset the module-level audit log (tests only)."""
    _default_log.reset()


def record(
    event_type: str,
    principal: Dict[str, Any],
    scope: Dict[str, Any],
    action: str,
    outcome: str,
    payload: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Append an audit record to the default log."""
    return _default_log.record(event_type, principal, scope, action, outcome, payload)


def verify_chain(records: List[Dict[str, Any]]) -> bool:
    """Verify an audit chain."""
    return AuditLog.verify_chain(records)
