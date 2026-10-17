"""Activation primitive — dormant-when-off, explicit, frozen, loud on typos.

Mandatory pair per gated feature: flag_off_is_noop + flag_on_changes_behavior.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

import pytest

from app.core.activation import (
    ActivationAdapter,
    ActivationError,
    ActivationFlag,
    emit_block_execution_note,
)


def _flag(monkeypatch, default: bool = False) -> ActivationFlag:
    return ActivationFlag("test_feature", "TEST_FEATURE_ENABLED", default=default)


def _adapter(flag: ActivationFlag, calls: list) -> ActivationAdapter:
    def when_on(*args: Any, **kwargs: Any) -> str:
        calls.append((args, kwargs))
        return "active"

    return ActivationAdapter(flag, when_on=when_on)


def test_flag_off_is_noop(monkeypatch):
    """OFF: the adapter never invokes the feature and returns the dormant result."""
    monkeypatch.delenv("TEST_FEATURE_ENABLED", raising=False)
    flag = _flag(monkeypatch)
    calls: list = []
    adapter = _adapter(flag, calls)
    assert adapter.apply("x", key="y") is None
    assert adapter.apply("x", key="y") is None
    assert calls == []


def test_flag_on_changes_behavior(monkeypatch):
    """ON: the feature runs and the result differs from the dormant path."""
    monkeypatch.setenv("TEST_FEATURE_ENABLED", "1")
    flag = _flag(monkeypatch)
    calls: list = []
    adapter = _adapter(flag, calls)
    assert adapter.apply("x", key="y") == "active"
    assert len(calls) == 1


def test_flag_off_path_is_byte_for_byte_the_unadaptered_path(monkeypatch):
    """The noop invariant: wrapping a path in the adapter changes nothing."""

    def path(value: int) -> Dict[str, Any]:
        out = {"value": value, "work": value * 2}
        adapter.apply(value)
        return out

    monkeypatch.delenv("TEST_FEATURE_ENABLED", raising=False)
    flag = _flag(monkeypatch)
    calls: list = []
    adapter = _adapter(flag, calls)
    before = {"value": 3, "work": 6}
    assert path(3) == before
    assert calls == []


def test_invalid_flag_value_is_loud(monkeypatch):
    monkeypatch.setenv("TEST_FEATURE_ENABLED", "banana")
    flag = _flag(monkeypatch)
    with pytest.raises(ActivationError) as exc:
        _ = flag.enabled
    assert exc.value.code == "activation_flag_invalid_value"


def test_require_refuses_when_off(monkeypatch):
    monkeypatch.delenv("TEST_FEATURE_ENABLED", raising=False)
    flag = _flag(monkeypatch)
    calls: list = []
    adapter = _adapter(flag, calls)
    with pytest.raises(ActivationError) as exc:
        adapter.require()
    assert exc.value.code == "activation_flag_off"


def test_flag_is_frozen_after_first_read(monkeypatch):
    monkeypatch.delenv("TEST_FEATURE_ENABLED", raising=False)
    flag = _flag(monkeypatch)
    assert flag.enabled is False
    monkeypatch.setenv("TEST_FEATURE_ENABLED", "1")
    assert flag.enabled is False  # frozen: mid-run toggles do not apply


# -- the wired adoption: block execution audit note -------------------------


class _MiniBlock:
    """Minimal stand-in exercising the same gated call site as TypedBlock.execute."""

    name = "mini_block"

    def execute(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {"block": self.name, "status": "success"}
        status = result.get("status", "ok")
        emit_block_execution_note(self.name, "req-1", str(status))
        return result


def _arm_wired_flag(monkeypatch, value: str | None) -> None:
    """Inject a fresh, unfrozen flag + adapter for the wired call site."""
    import app.core.activation as activation

    if value is None:
        monkeypatch.delenv("BLOCK_EXECUTION_AUDIT_ENABLED", raising=False)
    else:
        monkeypatch.setenv("BLOCK_EXECUTION_AUDIT_ENABLED", value)
    fresh = ActivationFlag("block_execution_audit", "BLOCK_EXECUTION_AUDIT_ENABLED")
    monkeypatch.setattr(activation, "_BLOCK_EXECUTION_AUDIT", fresh)
    monkeypatch.setattr(
        activation,
        "_AUDIT_ADAPTER",
        ActivationAdapter(fresh, when_on=activation._emit_execution_note),
    )


def test_block_execution_audit_off_is_noop(monkeypatch, caplog):
    _arm_wired_flag(monkeypatch, None)
    with caplog.at_level(logging.INFO):
        out = _MiniBlock().execute()
    assert out == {"block": "mini_block", "status": "success"}
    assert not [r for r in caplog.records if "block execution audit" in r.getMessage()]


def test_block_execution_audit_on_changes_behavior(monkeypatch, caplog):
    _arm_wired_flag(monkeypatch, "1")
    with caplog.at_level(logging.INFO):
        out = _MiniBlock().execute()
    assert out == {"block": "mini_block", "status": "success"}
    audit = [r for r in caplog.records if "block execution audit" in r.getMessage()]
    assert len(audit) == 1
    assert "mini_block" in audit[0].getMessage()
