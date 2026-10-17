"""Tests for the thin MLflow wrapper.

The wrapper must:
  * Construct without raising even when MLflow isn't installed.
  * Treat an empty/unset `MLFLOW_TRACKING_URI` as "no-op mode".
  * Yield a stand-in run object from `start_run` under no-op mode so
    callers can `with tracker.start_run(...)` unconditionally.
  * Optionally exercise a real MLflow round-trip when the SDK is
    importable and a file-based tracking URI is configured.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from app.core.mlflow_tracker import MLflowTracker, _NoopRun, tracker


@pytest.fixture(autouse=True)
def _clear_tracking_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default to no-op mode unless a test opts in."""
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "")


def test_constructor_does_not_raise_under_noop() -> None:
    t = MLflowTracker(experiment_name="test-noop")
    # Construction is cheap and side-effect-free; no env touched yet.
    assert t.experiment_name == "test-noop"


def test_is_active_false_when_uri_unset() -> None:
    t = MLflowTracker()
    assert t.is_active() is False


def test_start_run_yields_noop_object_under_noop() -> None:
    t = MLflowTracker()
    with t.start_run("run-1") as run:
        assert isinstance(run, _NoopRun)
        assert run.run_name == "run-1"
        # Logging methods must not raise — they're no-ops.
        t.log_param("k", "v")
        t.log_params({"a": 1, "b": 2})
        t.log_metric("loss", 0.42)
        t.log_metrics({"acc": 0.9, "f1": 0.85})


def test_log_artifact_noop_does_not_raise(tmp_path) -> None:
    t = MLflowTracker()
    fake = tmp_path / "fake.txt"
    fake.write_text("hello")
    # Even though the file exists, no-op mode skips the call entirely.
    t.log_artifact(str(fake))


def test_module_singleton_is_tracker_instance() -> None:
    assert isinstance(tracker, MLflowTracker)


# ---------------------------------------------------------------------
# Real-backend smoke test — always runs; mlflow is a pinned dependency.
# ---------------------------------------------------------------------


def test_real_backend_round_trip(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Exercise a real start_run + log_metric.

    mlflow is pinned in requirements.txt, so it is present wherever this
    suite is meant to run. It used to importorskip -- which meant the one
    test that touches real mlflow reported green on every environment that
    did not have it, including any that was supposed to.
    """
    import mlflow  # noqa: F401

    # A sqlite backend, not a file: URI. MLflow 3 refuses the filesystem
    # store outright ("in maintenance mode ... migrate to a database
    # backend"), and MLflowTracker catches that and falls back to a no-op --
    # so the file: URI this used to pass made the tracker silently do
    # nothing while the test still called it "the real backend".
    uri = f"sqlite:///{tmp_path}/mlflow.db"
    monkeypatch.setenv("MLFLOW_TRACKING_URI", uri)

    t = MLflowTracker(experiment_name="cerebrum-tests")
    assert t.is_active() is True

    with t.start_run("smoke") as run:
        # Real ActiveRun has a non-empty .info.run_id.
        assert run.info.run_id  # truthy, non-empty string
        t.log_param("model", "xgboost")
        t.log_metric("auc", 0.91)
        t.log_metrics({"precision": 0.88, "recall": 0.83})
