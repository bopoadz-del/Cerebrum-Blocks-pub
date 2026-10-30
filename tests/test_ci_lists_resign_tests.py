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


# --- ST-6c: re-sign.yml key handling, pinned by parsing the workflow as YAML ---
# (a) the KEY_FILE path step exports a $RUNNER_TEMP/... path via $GITHUB_ENV;
# (b) umask 077 runs before the key is written to $KEY_FILE;
# (c) the key-removal step runs under if: always();
# (d) the key-removal step comes after the commit step.
# Helpers return None/-1 for "not found" so a mutated workflow fails as an
# AssertionError in the test, never as a crash in the helper.

import re

RESIGN = REPO / ".github" / "workflows" / "re-sign.yml"
RESIGN_JOB = "re-sign"

_KEY_PATH_EXPORT = re.compile(
    r"""^echo\s+["']?KEY_FILE=\$\{?RUNNER_TEMP\}?/[^\s"'$]+["']?\s*>>\s*["']?\$\{?GITHUB_ENV\}?["']?$"""
)
_KEY_WRITE = re.compile(r""">\s*["']?\$\{?KEY_FILE\}?["']?\s*$""")
_KEY_RM = re.compile(r"""^rm\s+(-\w+\s+)*["']?\$\{?KEY_FILE\}?["']?$""")


def _steps(workflow: dict, job_id: str) -> list[dict]:
    job = (workflow.get("jobs") or {}).get(job_id) or {}
    return [s for s in (job.get("steps") or []) if isinstance(s, dict)]


def _run_lines(step: dict) -> list[str]:
    run = step.get("run")
    if not isinstance(run, str):
        return []
    return [ln.strip() for ln in run.splitlines() if ln.strip() and not ln.strip().startswith("#")]


def _index(steps: list[dict], pred) -> int:
    for i, step in enumerate(steps):
        if any(pred(ln) for ln in _run_lines(step)):
            return i
    return -1


def key_path_step(steps: list[dict]) -> int:
    return _index(steps, lambda ln: bool(_KEY_PATH_EXPORT.match(ln)))


def key_write_step(steps: list[dict]) -> int:
    return _index(steps, lambda ln: bool(_KEY_WRITE.search(ln)))


def key_rm_step(steps: list[dict]) -> int:
    return _index(steps, lambda ln: bool(_KEY_RM.match(ln)))


def commit_step(steps: list[dict]) -> int:
    return _index(steps, lambda ln: ln.startswith("git commit"))


def umask_before_write(step: dict) -> bool:
    lines = _run_lines(step)
    umask = [i for i, ln in enumerate(lines) if re.fullmatch(r"umask\s+0?077", ln)]
    write = [i for i, ln in enumerate(lines) if _KEY_WRITE.search(ln)]
    return bool(umask) and bool(write) and umask[0] < write[0]


def runs_always(step: dict) -> bool:
    cond = str(step.get("if", "")).strip()
    cond = re.sub(r"^\$\{\{\s*(.*?)\s*\}\}$", r"\1", cond)
    return cond == "always()"


def _resign_steps() -> list[dict]:
    return _steps(yaml.safe_load(RESIGN.read_text(encoding="utf-8")), RESIGN_JOB)


def test_resign_key_path_is_runner_temp_exported_to_github_env():
    steps = _resign_steps()
    i = key_path_step(steps)
    assert i >= 0, "no step exports KEY_FILE=$RUNNER_TEMP/... to $GITHUB_ENV"
    assert i < key_write_step(steps), "KEY_FILE must be exported before the key is written"


def test_resign_umask_077_before_key_write():
    steps = _resign_steps()
    w = key_write_step(steps)
    assert w >= 0, "no step writes the key to $KEY_FILE"
    assert umask_before_write(steps[w]), "umask 077 must precede the write to $KEY_FILE"


def test_resign_key_rm_step_runs_always():
    steps = _resign_steps()
    r = key_rm_step(steps)
    assert r >= 0, "no step removes $KEY_FILE"
    assert runs_always(steps[r]), "the key-removal step must have if: always()"


def test_resign_key_rm_step_after_commit_step():
    steps = _resign_steps()
    r, c = key_rm_step(steps), commit_step(steps)
    assert c >= 0, "no commit step found"
    assert r > c, f"key-removal step (index {r}) must come after the commit step (index {c})"


def test_resign_helpers_two_inputs_two_results():
    good = [
        {"run": 'echo "KEY_FILE=$RUNNER_TEMP/k.pem" >> "$GITHUB_ENV"'},
        {"run": 'umask 077\nprintf x > "$KEY_FILE"'},
        {"run": 'git commit -m x'},
        {"if": "always()", "run": 'rm -f "$KEY_FILE"'},
    ]
    bad = [
        {"run": 'echo "KEY_FILE=$GITHUB_WORKSPACE/k.pem" >> "$GITHUB_ENV"'},
        {"run": 'printf x > "$KEY_FILE"\numask 077'},
        {"run": 'rm -f "$KEY_FILE"'},
        {"run": 'git commit -m x'},
    ]
    assert (key_path_step(good), key_path_step(bad)) == (0, -1)
    assert (umask_before_write(good[1]), umask_before_write(bad[1])) == (True, False)
    assert (runs_always(good[3]), runs_always(bad[2])) == (True, False)
    assert (runs_always({"if": "${{ always() }}"}), runs_always({"if": "success()"})) == (True, False)
    assert (key_rm_step(good) > commit_step(good), key_rm_step(bad) > commit_step(bad)) == (True, False)
    assert key_path_step([{"run": 'echo "KEY_FILE=$RUNNER_TEMP/k.pem" >> "$GITHUB_OUTPUT"'}]) == -1
