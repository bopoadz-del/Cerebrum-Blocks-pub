"""Tests for the Phase-2 retrain task (`app/tasks/learning_retrain.py`).

These pin the synchronous fallback so the codebase keeps working when
Celery is not configured (which is the case in CI). The Celery branch
is exercised indirectly by verifying the task object exposes the same
``.delay()`` / ``.apply()`` surface area the rest of the code calls.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from app.tasks.learning_retrain import (
    _fit_coefficients,
    _retrain_formula_impl,
    retrain_formula,
)


# ── _fit_coefficients ───────────────────────────────────────────────────


def test_fit_coefficients_clean_signal_returns_multiplier():
    history = [{"predicted": 100.0, "actual": 120.0} for _ in range(10)]
    coeffs = _fit_coefficients(history)
    assert "multiplier" in coeffs
    assert coeffs["multiplier"] == pytest.approx(1.2, rel=1e-4)


def test_fit_coefficients_too_few_samples_returns_empty():
    assert _fit_coefficients([]) == {}
    assert _fit_coefficients(
        [{"predicted": 100.0, "actual": 110.0}] * 4
    ) == {}


def test_fit_coefficients_zero_actuals_returns_empty():
    history = [{"predicted": 100.0, "actual": 0.0} for _ in range(20)]
    assert _fit_coefficients(history) == {}


def test_fit_coefficients_zero_predicted_returns_empty():
    history = [{"predicted": 0.0, "actual": 50.0} for _ in range(20)]
    assert _fit_coefficients(history) == {}


def test_fit_coefficients_clamped_when_outside_safe_band():
    """Multiplier > 2.0 — refuse the fit (treat as bad signal)."""
    history = [{"predicted": 10.0, "actual": 100.0} for _ in range(20)]
    assert _fit_coefficients(history) == {}

    # And < 0.5 — also refuse.
    history_low = [{"predicted": 100.0, "actual": 30.0} for _ in range(20)]
    assert _fit_coefficients(history_low) == {}


# ── _retrain_formula_impl — synchronous orchestration ───────────────────


class _FakeEngine:
    """Stand-in for the LearningEngineBlock that the retrain task
    fetches via get_block_instance. Records what set_coefficients was
    called with so tests can assert on persistence."""

    def __init__(self, history: List[Dict[str, Any]]):
        self._history = history
        self.persisted: Dict[str, Dict[str, float]] = {}

    def get_correction_history(self, formula_id: str) -> List[Dict[str, Any]]:
        return list(self._history)

    def set_coefficients(self, formula_id: str, coefficients: Dict[str, float]) -> None:
        self.persisted[formula_id] = dict(coefficients)

    def get_coefficient_mae(self, formula_id, holdout):
        # Pretend the existing fit is terrible so any new fit "wins".
        return float("inf")


def _patch_engine(monkeypatch, engine):
    """Force `app.dependencies.get_block_instance` to return our fake."""
    import app.dependencies as deps
    monkeypatch.setattr(deps, "get_block_instance", lambda name: engine)


def test_retrain_skipped_when_history_empty(monkeypatch):
    engine = _FakeEngine([])
    _patch_engine(monkeypatch, engine)

    result = _retrain_formula_impl("concrete_cost")
    assert result["status"] == "skipped"
    assert result["reason"] == "insufficient_history"
    assert result["formula_id"] == "concrete_cost"


def test_retrain_updated_with_clean_signal(monkeypatch):
    """50-row clean signal where actual = pred * 1.2 must produce a
    persisted multiplier of ~1.2 and report status: updated."""
    history = [{"predicted": 100.0, "actual": 120.0} for _ in range(50)]
    engine = _FakeEngine(history)
    _patch_engine(monkeypatch, engine)

    result = _retrain_formula_impl("concrete_cost")
    assert result["status"] == "updated"
    assert result["formula_id"] == "concrete_cost"
    assert result["coefficients"]["multiplier"] == pytest.approx(1.2, rel=1e-4)
    assert engine.persisted["concrete_cost"]["multiplier"] == pytest.approx(
        1.2, rel=1e-4,
    )


def test_retrain_skipped_when_fit_yields_no_coefficients(monkeypatch):
    """30 rows but with a multiplier outside [0.5, 2.0] → skipped."""
    history = [{"predicted": 10.0, "actual": 100.0} for _ in range(40)]
    engine = _FakeEngine(history)
    _patch_engine(monkeypatch, engine)

    result = _retrain_formula_impl("bad_formula")
    assert result["status"] == "skipped"
    assert result["reason"] == "fit_yielded_no_coefficients"


# ── task surface area — works with or without Celery ───────────────────


def test_retrain_task_has_delay_and_apply():
    """Whether the runtime is Celery- or fallback-backed, the call site
    must be able to use both ``.delay()`` and ``.apply()`` without
    branching."""
    assert hasattr(retrain_formula, "delay")
    assert callable(retrain_formula.delay)
    assert hasattr(retrain_formula, "apply")
    assert callable(retrain_formula.apply)


def test_retrain_delay_executes_synchronously_in_fallback(monkeypatch):
    """Without Celery installed/configured, .delay should run the task
    inline and return its dict. (Under Celery it would return an
    AsyncResult — that branch isn't exercised here.)"""
    engine = _FakeEngine([])
    _patch_engine(monkeypatch, engine)

    # Skip the test if Celery is actually wired (unlikely in CI).
    if type(retrain_formula).__name__ != "_SyncTask":
        pytest.skip("Celery is configured — fallback branch not exercised")

    result = retrain_formula.delay("concrete_cost")
    assert isinstance(result, dict)
    assert result["status"] == "skipped"


def test_retrain_apply_passes_through_args(monkeypatch):
    engine = _FakeEngine([])
    _patch_engine(monkeypatch, engine)

    if type(retrain_formula).__name__ != "_SyncTask":
        pytest.skip("Celery is configured — fallback branch not exercised")

    result = retrain_formula.apply(args=["concrete_cost"])
    assert isinstance(result, dict)
    assert result["formula_id"] == "concrete_cost"
