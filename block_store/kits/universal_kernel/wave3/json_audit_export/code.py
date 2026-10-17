"""Neutral JSON audit export primitives."""

from __future__ import annotations

import json
from typing import Any, Dict, List


class AuditExportError(ValueError):
    """Raised when audit records cannot be exported."""


REQUIRED_KEYS = {
    "event_type",
    "principal",
    "action",
    "outcome",
    "timestamp",
    "record_hash",
}


def _validate_record(record: Any) -> None:
    if not isinstance(record, dict):
        raise AuditExportError("audit record must be a dict")
    missing = REQUIRED_KEYS - set(record.keys())
    if missing:
        raise AuditExportError(
            f"audit record missing required keys: {sorted(missing)}"
        )


def export_audit(
    records: List[Dict[str, Any]],
    include_payload: bool = True,
    pretty: bool = False,
) -> str:
    """Export audit records as stable canonical JSON.

    Args:
        records: List of audit-record dicts.
        include_payload: When False, redact any ``payload`` field.
        pretty: When True, indent the JSON output.

    Returns:
        Canonical JSON string.

    Raises:
        AuditExportError: When records are malformed.
    """
    if not isinstance(records, list):
        raise AuditExportError("records must be a list")

    cleaned: List[Dict[str, Any]] = []
    for record in records:
        _validate_record(record)
        copy = dict(record)
        if not include_payload:
            copy.pop("payload", None)
        cleaned.append(copy)

    return json.dumps(
        cleaned,
        sort_keys=True,
        indent=2 if pretty else None,
        ensure_ascii=False,
    )
