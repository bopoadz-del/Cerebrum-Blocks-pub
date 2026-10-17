"""Tests for the neutral JSON audit export sub-kit."""

import json

import pytest

from block_store.kits.universal_kernel.wave3.json_audit_export import (
    AuditExportError,
    export_audit,
)


def _valid_record(payload: bool = True):
    record = {
        "event_type": "access",
        "principal": "user-1",
        "action": "read",
        "outcome": "success",
        "timestamp": "2024-01-01T00:00:00Z",
        "record_hash": "abc123",
    }
    if payload:
        record["payload"] = {"resource": "doc-1"}
    return record


def test_export_audit_valid():
    records = [_valid_record()]
    text = export_audit(records)
    data = json.loads(text)
    assert data[0]["principal"] == "user-1"


def test_export_audit_redact_payload():
    records = [_valid_record()]
    text = export_audit(records, include_payload=False)
    data = json.loads(text)
    assert "payload" not in data[0]


def test_export_audit_pretty():
    text = export_audit([_valid_record()], pretty=True)
    assert "\n" in text


def test_invalid_record_raises():
    with pytest.raises(AuditExportError):
        export_audit([{"principal": "user-1"}])


def test_records_must_be_list():
    with pytest.raises(AuditExportError):
        export_audit("not-a-list")  # type: ignore[arg-type]
