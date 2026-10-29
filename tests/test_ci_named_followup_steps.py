"""Follow-up pins: ST-7 restored-data tests and the ST-AWS-OIDC deploy pin
must each run in a NAMED, BLOCKING step of the Backend job that still runs
after an earlier (ruled-red) step fails.

Backend names test files explicitly, so a file not listed there never runs
in that job. A listed step without ``if: !cancelled()`` placed after a red
step is SKIPPED, which looks like coverage but runs nothing; a step with
``continue-on-error`` can never fail the job. Both count as absent here.

The workflow is parsed as YAML, so comments and other jobs are not mistaken
for a listing. Branch protection is not configured on this repository; the
Backend job is "required" in the sense that it has no continue-on-error and
its failure fails the CI run.
"""
from __future__ import annotations

import shlex
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
BACKEND_JOB = "backend"
RUNS_AFTER_FAILURE = {"${{ !cancelled() }}", "!cancelled()", "${{ always() }}", "always()"}

# step name -> test files it must run
REQUIRED_STEPS = {
    "ST-7 restored-data gates (ST-7)": (
        "tests/test_no_dangling_data_refs.py",
        "tests/test_st7_restored_data.py",
        "tests/core/test_domain_pack_loader_st7.py",
    ),
    "Deploy workflow OIDC pin (ST-AWS-OIDC)": ("tests/test_deploy_aws_oidc.py",),
}


def _pytest_files(run: str) -> set[str]:
    found: set[str] = set()
    for line in run.replace("\\\n", " ").splitlines():
        try:
            tokens = shlex.split(line, comments=True)
        except ValueError:
            continue
        if "pytest" in tokens:
            found.update(t for t in tokens if t.startswith("tests/") and t.endswith(".py"))
    return found


def blocking_named_steps(workflow: dict, job_id: str) -> dict[str, set[str]]:
    """name -> pytest files, for steps of job_id that run after a red step
    and can fail the job. Steps failing either condition are dropped."""
    job = (workflow.get("jobs") or {}).get(job_id) or {}
    if job.get("continue-on-error"):
        return {}
    out: dict[str, set[str]] = {}
    for step in job.get("steps") or []:
        run, name = step.get("run"), step.get("name")
        if not isinstance(run, str) or not isinstance(name, str):
            continue
        if step.get("continue-on-error"):
            continue
        if str(step.get("if", "")).strip() not in RUNS_AFTER_FAILURE:
            continue
        out[name] = out.get(name, set()) | _pytest_files(run)
    return out


def _load() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", sorted(REQUIRED_STEPS))
def test_named_step_runs_its_files_in_backend(name):
    steps = blocking_named_steps(_load(), BACKEND_JOB)
    assert name in steps, f"no blocking, run-after-failure Backend step named {name!r}"
    missing = set(REQUIRED_STEPS[name]) - steps[name]
    assert not missing, f"step {name!r} does not run {sorted(missing)}"


# ---- helper behaviour (two inputs, two outputs) ----
def _wf(steps, job_id="backend", **job_extra):
    return {"jobs": {job_id: {"steps": steps, **job_extra}}}


def _s(name, run, **extra):
    return {"name": name, "run": run, "if": "${{ !cancelled() }}", **extra}


def test_helper_two_inputs_two_outputs():
    a = blocking_named_steps(_wf([_s("A", "pytest -q tests/test_a.py")]), "backend")
    b = blocking_named_steps(_wf([_s("B", "pytest -q tests/test_b.py tests/x/test_c.py")]), "backend")
    assert a == {"A": {"tests/test_a.py"}}
    assert b == {"B": {"tests/test_b.py", "tests/x/test_c.py"}}


def test_helper_drops_step_without_run_after_failure_guard():
    step = {"name": "A", "run": "pytest -q tests/test_a.py"}
    assert blocking_named_steps(_wf([step]), "backend") == {}
    step_false = dict(step, **{"if": "${{ false }}"})
    assert blocking_named_steps(_wf([step_false]), "backend") == {}


def test_helper_drops_continue_on_error_step_and_job():
    wf = _wf([_s("A", "pytest -q tests/test_a.py", **{"continue-on-error": True})])
    assert blocking_named_steps(wf, "backend") == {}
    wf2 = _wf([_s("A", "pytest -q tests/test_a.py")], **{"continue-on-error": True})
    assert blocking_named_steps(wf2, "backend") == {}


def test_helper_ignores_other_jobs_and_comments():
    wf = _wf([_s("A", "pytest -q tests/test_a.py")], job_id="full-suite")
    assert blocking_named_steps(wf, "backend") == {}
    wf2 = _wf([_s("A", "echo hi  # pytest tests/test_a.py")])
    assert blocking_named_steps(wf2, "backend") == {"A": set()}
