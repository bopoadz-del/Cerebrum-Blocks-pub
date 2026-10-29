"""ST-6b: the re-sign/rotation test files must actually run in Backend CI.

CI names test files explicitly rather than running tests/, so a test file
that is not listed in a Backend step never runs there and its mutant kills
are local-only. This parses the workflow as YAML (comments and other jobs
are therefore not mistaken for a listing) and asserts each file is passed
to pytest by a run command of a Backend-job step that can fail the job.
"""
from __future__ import annotations

import shlex
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
BACKEND_JOB = "backend"

# Test files added by ST-5/ST-6/ST-6b, plus this guard itself.
REQUIRED = (
    "tests/test_rotate_publisher_key.py",
    "tests/test_refresh_kit_bundles.py",
    "tests/test_ci_lists_resign_tests.py",
)


def pytest_files_run_by_job(workflow: dict, job_id: str) -> set[str]:
    """Paths passed to pytest in run commands of blocking steps of job_id."""
    job = (workflow.get("jobs") or {}).get(job_id) or {}
    found: set[str] = set()
    for step in job.get("steps") or []:
        run = step.get("run")
        if not isinstance(run, str) or step.get("continue-on-error"):
            continue
        for line in run.replace("\\\n", " ").splitlines():
            try:
                tokens = shlex.split(line, comments=True)
            except ValueError:
                continue
            if "pytest" not in tokens:
                continue
            found.update(t for t in tokens if t.startswith("tests/") and t.endswith(".py"))
    return found


def _load() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", REQUIRED)
def test_required_file_exists(path):
    assert (REPO / path).is_file(), f"{path} named here but missing on disk"


@pytest.mark.parametrize("path", REQUIRED)
def test_required_file_runs_in_backend_job(path):
    listed = pytest_files_run_by_job(_load(), BACKEND_JOB)
    assert path in listed, f"{path} is not run by any blocking step of job '{BACKEND_JOB}'"


def _wf(job_id: str, run: str, **step_extra) -> dict:
    return {"jobs": {job_id: {"steps": [{"name": "s", "run": run, **step_extra}]}}}


def test_helper_two_inputs_two_results():
    a = pytest_files_run_by_job(_wf("backend", "pytest -q tests/test_a.py"), "backend")
    b = pytest_files_run_by_job(_wf("backend", "pytest -q tests/test_b.py"), "backend")
    assert a == {"tests/test_a.py"} and b == {"tests/test_b.py"}


def test_helper_ignores_other_jobs():
    wf = _wf("frontend", "pytest -q tests/test_a.py")
    assert pytest_files_run_by_job(wf, "backend") == set()
    assert pytest_files_run_by_job(wf, "frontend") == {"tests/test_a.py"}


def test_helper_ignores_continue_on_error_steps():
    wf = _wf("backend", "pytest -q tests/test_a.py", **{"continue-on-error": True})
    assert pytest_files_run_by_job(wf, "backend") == set()


def test_helper_ignores_shell_comments_and_non_pytest_lines():
    run = "# pytest -q tests/test_a.py\necho tests/test_b.py\npytest tests/test_c.py \\\n  tests/test_d.py"
    assert pytest_files_run_by_job(_wf("backend", run), "backend") == {
        "tests/test_c.py",
        "tests/test_d.py",
    }


def test_helper_yaml_comment_is_not_a_listing():
    text = "jobs:\n  backend:\n    steps:\n      # - run: pytest tests/test_a.py\n      - run: echo hi\n"
    assert pytest_files_run_by_job(yaml.safe_load(text), "backend") == set()
