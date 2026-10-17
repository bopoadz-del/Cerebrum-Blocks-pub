"""Thin MLflow wrapper that no-ops when MLflow isn't configured.

The real MLflow SDK is heavy (pulls sqlalchemy, alembic, gunicorn). We
keep imports lazy so the FastAPI app starts fast and so unit tests in
environments without MLflow installed still pass.

When `mlflow` is missing OR the `MLFLOW_TRACKING_URI` env var is empty
or unset, every public method becomes a no-op and `start_run` yields a
fake run object. A single warning is logged at first call so we don't
spam logs in production.
"""

from __future__ import annotations

import logging
import os
import threading
from contextlib import contextmanager
from typing import Any, Iterator, Mapping

logger = logging.getLogger(__name__)

_warning_lock = threading.Lock()
_warned_once = False


def _warn_once() -> None:
    """Emit the no-op warning at most once per process."""
    global _warned_once
    with _warning_lock:
        if _warned_once:
            return
        _warned_once = True
        logger.warning("MLflow not configured — tracker is no-op")


class _NoopRun:
    """Stand-in object yielded by `start_run` when MLflow is inactive.

    Mirrors the small subset of attributes callers tend to read off the
    real `mlflow.ActiveRun.info` (`run_id`, `experiment_id`) so tests
    and consumers can introspect without conditionals.
    """

    def __init__(self, run_name: str | None = None) -> None:
        self.info = _NoopRunInfo(run_name=run_name)
        self.run_name = run_name

    def __repr__(self) -> str:
        return f"<_NoopRun run_name={self.run_name!r}>"


class _NoopRunInfo:
    def __init__(self, run_name: str | None = None) -> None:
        self.run_id = "noop-run"
        self.experiment_id = "noop-experiment"
        self.run_name = run_name


def _import_mlflow() -> Any | None:
    """Lazy-import mlflow; return the module or None if unavailable."""
    try:
        import mlflow  # type: ignore[import-not-found]
    except Exception:  # pragma: no cover — defensive
        return None
    return mlflow


class MLflowTracker:
    """Thin wrapper around the MLflow Python SDK.

    Construction never raises. Every method tolerates a missing backend
    by short-circuiting to a no-op and logging a single warning. Use
    `is_active()` to check whether logs are actually being persisted.
    """

    def __init__(self, experiment_name: str = "cerebrum-default") -> None:
        self.experiment_name = experiment_name
        self._configured: bool | None = None  # cached on first call
        self._mlflow: Any | None = None

    # ------------------------------------------------------------------
    # Configuration / readiness
    # ------------------------------------------------------------------
    def _resolve(self) -> Any | None:
        """Return the live mlflow module if usable, else None.

        Caches the decision so we only attempt the import + experiment
        setup once per tracker instance.
        """
        if self._configured is False:
            return None
        if self._configured is True:
            return self._mlflow

        tracking_uri = os.getenv("MLFLOW_TRACKING_URI", "").strip()
        if not tracking_uri:
            self._configured = False
            _warn_once()
            return None

        mlflow = _import_mlflow()
        if mlflow is None:
            self._configured = False
            _warn_once()
            return None

        try:
            mlflow.set_tracking_uri(tracking_uri)
            mlflow.set_experiment(self.experiment_name)
        except Exception:
            # Backend mis-configured (bad URI, permissions). Degrade to
            # no-op rather than crashing the calling code path.
            logger.exception("MLflow setup failed — falling back to no-op")
            self._configured = False
            return None

        self._configured = True
        self._mlflow = mlflow
        return mlflow

    def is_active(self) -> bool:
        """True iff the real MLflow backend is reachable and configured."""
        return self._resolve() is not None

    # ------------------------------------------------------------------
    # Run lifecycle
    # ------------------------------------------------------------------
    @contextmanager
    def start_run(self, run_name: str | None = None) -> Iterator[Any]:
        """Context manager wrapping `mlflow.start_run` / `mlflow.end_run`.

        Yields the active run object (real `mlflow.ActiveRun` when the
        backend is configured, else a `_NoopRun` stand-in). On exit, the
        run is always ended — whether success or exception — to mirror
        MLflow's own behaviour.
        """
        mlflow = self._resolve()
        if mlflow is None:
            yield _NoopRun(run_name=run_name)
            return

        run = mlflow.start_run(run_name=run_name)
        try:
            yield run
        finally:
            try:
                mlflow.end_run()
            except Exception:
                logger.exception("mlflow.end_run() raised — swallowing")

    # ------------------------------------------------------------------
    # Logging — params / metrics / artifacts
    # ------------------------------------------------------------------
    def log_param(self, key: str, value: Any) -> None:
        mlflow = self._resolve()
        if mlflow is None:
            return
        try:
            mlflow.log_param(key, value)
        except Exception:
            logger.exception("mlflow.log_param failed (key=%s)", key)

    def log_params(self, params: Mapping[str, Any]) -> None:
        mlflow = self._resolve()
        if mlflow is None:
            return
        try:
            mlflow.log_params(dict(params))
        except Exception:
            logger.exception("mlflow.log_params failed")

    def log_metric(self, key: str, value: float, step: int | None = None) -> None:
        mlflow = self._resolve()
        if mlflow is None:
            return
        try:
            mlflow.log_metric(key, value, step=step)
        except Exception:
            logger.exception("mlflow.log_metric failed (key=%s)", key)

    def log_metrics(self, metrics: Mapping[str, float]) -> None:
        mlflow = self._resolve()
        if mlflow is None:
            return
        try:
            mlflow.log_metrics(dict(metrics))
        except Exception:
            logger.exception("mlflow.log_metrics failed")

    def log_artifact(self, local_path: str) -> None:
        mlflow = self._resolve()
        if mlflow is None:
            return
        try:
            mlflow.log_artifact(local_path)
        except Exception:
            logger.exception("mlflow.log_artifact failed (path=%s)", local_path)


# Module-level singleton — import this from other modules instead of
# constructing your own tracker so the no-op warning stays one-shot.
tracker = MLflowTracker()


__all__ = ["MLflowTracker", "tracker"]
