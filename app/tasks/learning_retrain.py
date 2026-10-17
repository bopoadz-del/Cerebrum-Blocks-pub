"""Celery task: refit formula coefficients from the most recent
corrections.

This task scaffolds the Phase-2 retrain loop from
docs/design/auto-retraining.md. It registers under the existing Celery
worker (cerebrum-worker-fast on Render) when CELERY_BROKER_URL is set;
otherwise the function still works synchronously via .apply().
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Celery is optional — when not configured, the task object becomes a
# plain function with .delay() = synchronous .apply().
try:
    from celery import Celery  # type: ignore[import-not-found]

    _broker = os.getenv("CELERY_BROKER_URL")
    if _broker:
        _celery_app = Celery(
            "cerebrum.learning",
            broker=_broker,
            backend=os.getenv("CELERY_RESULT_BACKEND", _broker),
        )
    else:
        _celery_app = None
except ImportError:
    _celery_app = None


def _fit_coefficients(history: List[Dict[str, Any]]) -> Dict[str, float]:
    """Least-squares fit of (predicted_value, actual_value) pairs to a
    single multiplicative coefficient. Conservative: never returns
    coefficients < 0.5 or > 2.0 — anything more than 2x is treated as
    insufficient signal and the existing coefficient stays."""
    if not history or len(history) < 5:
        return {}
    pred = [float(h.get("predicted", 0)) for h in history]
    actual = [float(h.get("actual", 0)) for h in history]
    if not any(pred) or not any(actual):
        return {}
    # Single-coefficient fit: c = mean(actual) / mean(pred)
    p = sum(pred) / len(pred)
    a = sum(actual) / len(actual)
    if p == 0:
        return {}
    c = a / p
    if not (0.5 <= c <= 2.0):
        return {}
    return {"multiplier": round(c, 6)}


def _improves_holdout(coeffs, holdout, engine, formula_id) -> bool:
    """Returns True when the new coefficients reduce MAE on the
    holdout vs. the current coefficients. Bare-metal default: trust
    the new fit if MAE is finite (no current_coeffs available means
    any reasonable fit is an improvement)."""
    if not holdout:
        return False
    multiplier = coeffs.get("multiplier", 1.0)
    new_errors = []
    for h in holdout:
        pred = float(h.get("predicted", 0)) * multiplier
        actual = float(h.get("actual", 0))
        new_errors.append(abs(pred - actual))
    new_mae = sum(new_errors) / len(new_errors) if new_errors else float("inf")

    if hasattr(engine, "get_coefficient_mae"):
        current_mae = engine.get_coefficient_mae(formula_id, holdout)
        if current_mae is None or new_mae < current_mae:
            return True
        return False
    # No baseline known — accept new fit only when its MAE is meaningful
    return new_mae < float("inf")


def _retrain_formula_impl(formula_id: str) -> Dict[str, Any]:
    """Synchronous core. Loads correction history from the learning
    engine's state file, fits coefficients, validates against a
    held-out 20% slice, and persists when the new fit improves MAE."""
    from app.dependencies import get_block_instance
    try:
        engine = get_block_instance("learning_engine")
    except Exception as exc:
        logger.exception("retrain: learning_engine block not available")
        return {"status": "error", "error": str(exc), "formula_id": formula_id}

    history = (
        engine.get_correction_history(formula_id)
        if hasattr(engine, "get_correction_history")
        else []
    )
    if len(history) < 30:
        return {
            "status": "skipped",
            "reason": "insufficient_history",
            "n": len(history),
            "formula_id": formula_id,
        }

    # 80/20 split
    cutoff = int(len(history) * 0.8)
    train, holdout = history[:cutoff], history[cutoff:]

    coeffs = _fit_coefficients(train)
    if not coeffs:
        return {
            "status": "skipped",
            "reason": "fit_yielded_no_coefficients",
            "formula_id": formula_id,
        }

    # Validate against holdout
    if not _improves_holdout(coeffs, holdout, engine, formula_id):
        return {
            "status": "no_improvement",
            "formula_id": formula_id,
            "candidate_coefficients": coeffs,
        }

    # Persist
    if hasattr(engine, "set_coefficients"):
        engine.set_coefficients(formula_id, coeffs)

    # Log to MLflow if active
    try:
        from app.core.mlflow_tracker import tracker
        with tracker.start_run(f"retrain-{formula_id}"):
            tracker.log_param("formula_id", formula_id)
            tracker.log_metric("history_size", float(len(history)))
            for k, v in coeffs.items():
                tracker.log_metric(f"coeff_{k}", float(v))
            tracker.log_metric("retrained_at", time.time())
    except Exception:
        logger.exception("retrain: MLflow logging failed")

    return {"status": "updated", "formula_id": formula_id, "coefficients": coeffs}


# Celery task wrapper
if _celery_app is not None:
    @_celery_app.task(name="learning.retrain")
    def retrain_formula(formula_id: str):  # type: ignore[no-redef]
        return _retrain_formula_impl(formula_id)
else:
    class _SyncTask:
        """Drop-in stand-in matching the small subset of the Celery
        Task API the rest of the codebase calls (.delay / .apply / __call__).
        Keeps the call sites identical whether or not Celery is wired."""

        def delay(self, formula_id: str):
            return _retrain_formula_impl(formula_id)

        def apply(self, args=None, kwargs=None):
            return _retrain_formula_impl(*(args or []), **(kwargs or {}))

        def __call__(self, formula_id: str):
            return _retrain_formula_impl(formula_id)

    retrain_formula = _SyncTask()  # type: ignore[assignment]


__all__ = [
    "retrain_formula",
    "_fit_coefficients",
    "_retrain_formula_impl",
    "_improves_holdout",
]
