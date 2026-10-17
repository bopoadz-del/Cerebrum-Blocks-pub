"""Tests for the neutral audit evidence sub-kit."""

import pytest

from block_store.kits.universal_kernel.wave1.audit_evidence import (
    AuditIntegrityError,
    AuditLog,
    ZERO_HASH,
    record,
    reset_audit_log,
    verify_chain,
)


@pytest.fixture(autouse=True)
def _clean_audit_log():
    reset_audit_log()
    yield
    reset_audit_log()


PRINCIPAL = {"id": "principal-1"}
SCOPE = {"tenant_id": "tenant-1", "project_id": "project-1"}


def test_record_contains_hash_chain_fields():
    log = AuditLog()
    entry = log.record(
        event_type="login",
        principal=PRINCIPAL,
        scope=SCOPE,
        action="authenticate",
        outcome="success",
        payload={"ip": "127.0.0.1"},
    )
    assert entry["previous_hash"] == ZERO_HASH
    assert len(entry["record_hash"]) == 64
    assert entry["timestamp"]


def test_verify_chain_succeeds_for_intact_records():
    log = AuditLog()
    log.record("login", PRINCIPAL, SCOPE, "authenticate", "success")
    log.record("read", PRINCIPAL, SCOPE, "read_resource", "success")
    assert verify_chain(log.records()) is True


def test_tampered_record_detected():
    log = AuditLog()
    log.record("login", PRINCIPAL, SCOPE, "authenticate", "success")
    second = log.record("read", PRINCIPAL, SCOPE, "read_resource", "success")
    second["outcome"] = "tampered"
    with pytest.raises(AuditIntegrityError, match="tampered"):
        verify_chain(log.records())


def test_broken_chain_link_detected():
    log = AuditLog()
    log.record("login", PRINCIPAL, SCOPE, "authenticate", "success")
    second = log.record("read", PRINCIPAL, SCOPE, "read_resource", "success")
    second["previous_hash"] = "deadbeef"
    with pytest.raises(AuditIntegrityError, match="chain broken"):
        verify_chain(log.records())


def test_module_level_record_is_reachable():
    entry = record("login", PRINCIPAL, SCOPE, "authenticate", "success")
    assert entry["event_type"] == "login"
