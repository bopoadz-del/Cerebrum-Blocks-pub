"""Tests for the neutral billing / entitlement sub-kit."""

from datetime import datetime, timedelta, timezone

import pytest

from block_store.kits.universal_kernel.wave3.billing_entitlement import (
    Entitlement,
    EntitlementError,
    EntitlementExceeded,
    EntitlementLedger,
)


def test_check_entitlement_allowed():
    ledger = EntitlementLedger()
    ledger.set(Entitlement("p1", "feature-x", quota=10))
    result = ledger.check_entitlement("p1", "feature-x", required=3)
    assert result["allowed"] is True
    assert result["remaining"] == 10


def test_record_usage():
    ledger = EntitlementLedger()
    ledger.set(Entitlement("p1", "feature-x", quota=10))
    ledger.record_usage("p1", "feature-x", amount=4)
    assert ledger.check_entitlement("p1", "feature-x")["remaining"] == 6


def test_missing_entitlement_denies():
    ledger = EntitlementLedger()
    result = ledger.check_entitlement("p1", "feature-x")
    assert result["allowed"] is False
    assert result["reason"] == "entitlement not found"


def test_require_entitled_raises():
    ledger = EntitlementLedger()
    with pytest.raises(EntitlementExceeded):
        ledger.require_entitled("p1", "feature-x")


def test_quota_exceeded():
    ledger = EntitlementLedger()
    ledger.set(Entitlement("p1", "feature-x", quota=1))
    ledger.record_usage("p1", "feature-x")
    with pytest.raises(EntitlementExceeded):
        ledger.record_usage("p1", "feature-x")


def test_window_expired():
    ledger = EntitlementLedger()
    past = datetime.now(timezone.utc) - timedelta(days=2)
    ledger.set(
        Entitlement(
            "p1",
            "feature-x",
            quota=10,
            window_start=past - timedelta(days=1),
            window_end=past,
        )
    )
    result = ledger.check_entitlement("p1", "feature-x")
    assert result["allowed"] is False
    assert result["reason"] == "entitlement window expired"


def test_invalid_quota_raises():
    with pytest.raises(EntitlementError):
        Entitlement("p1", "feature-x", quota=-1)
