"""Tests for the neutral rate-limit guard sub-kit."""

import pytest

from block_store.kits.universal_kernel.wave1.rate_limit_guard import (
    record_and_check,
    reset_rate_limiter,
)


@pytest.fixture(autouse=True)
def _clean_limiter():
    reset_rate_limiter()
    yield
    reset_rate_limiter()


def test_request_within_limit_is_allowed():
    result = record_and_check("alice", "read", window_seconds=60, max_requests=3)
    assert result["allowed"] is True
    assert result["remaining"] == 2
    assert result["reset_at"] > 0


def test_exceeding_limit_returns_429_semantics():
    for _ in range(3):
        record_and_check("alice", "read", window_seconds=60, max_requests=3)
    result = record_and_check("alice", "read", window_seconds=60, max_requests=3)
    assert result["allowed"] is False
    assert result["remaining"] == 0


def test_identities_are_isolated():
    record_and_check("alice", "read", window_seconds=60, max_requests=1)
    result = record_and_check("bob", "read", window_seconds=60, max_requests=1)
    assert result["allowed"] is True


def test_actions_are_isolated():
    record_and_check("alice", "read", window_seconds=60, max_requests=1)
    result = record_and_check("alice", "write", window_seconds=60, max_requests=1)
    assert result["allowed"] is True


def test_invalid_window_or_max_raises():
    with pytest.raises(ValueError):
        record_and_check("alice", "read", window_seconds=0, max_requests=10)
    with pytest.raises(ValueError):
        record_and_check("alice", "read", window_seconds=10, max_requests=0)
