"""ST-1: the "Run every test file" CI step must be able to fail the job.

A step that masks its own exit status (continue-on-error, ``|| true``,
``set +e``, ``--continue-on-collection-errors``) reports a red suite as
green. The checker below is run on the real ci.yml and on parsed samples,
so a checker that never fires is itself caught.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_STEP_NAME = "Run every test file"
_JOB_ID = "full-suite"
# "exit 0" as a command anywhere in the script: after ";", "||", "&&", "|",
# "(", or at the start of any line (newline-separated, own line after pytest),
# with any amount of whitespace.
_EXIT_ZERO = re.compile(r"(?:^|[;&|(])[ \t]*exit[ \t]+0+(?![0-9])", re.MULTILINE)


def _masking_reasons(step: dict) -> list[str]:
    """Every way ``step`` can hide a failing exit status (empty = blocking)."""
    reasons: list[str] = []
    if "continue-on-error" in step and step["continue-on-error"] is not False:
        reasons.append("continue-on-error")
    run = str(step.get("run", ""))
    # strip comments so prose about the old setting is not a false hit
    code = "\n".join(line.split("#", 1)[0] for line in run.splitlines())
    if re.search(r"\|\|\s*true\b", code) or re.search(r"\|\|\s*:(\s|$)", code):
        reasons.append("|| true")
    if re.search(r"\bset\s+\+e\b", code):
        reasons.append("set +e")
    if _EXIT_ZERO.search(code):
        reasons.append("exit 0")
    if "--continue-on-collection-errors" in code:
        reasons.append("--continue-on-collection-errors")
    return reasons


def _find_steps(workflow: dict, name: str) -> list[dict]:
    found = []
    for job in (workflow.get("jobs") or {}).values():
        if job.get("continue-on-error") not in (None, False):
            # job-level masking also hides the step; surface it on each step
            found.extend({**s, "continue-on-error": True}
                         for s in job.get("steps") or [] if s.get("name") == name)
            continue
        found.extend(s for s in job.get("steps") or [] if s.get("name") == name)
    return found


def test_run_every_test_file_step_is_blocking():
    workflow = yaml.safe_load(_CI.read_text(encoding="utf-8"))
    steps = _find_steps(workflow, _STEP_NAME)
    assert len(steps) == 1, f"expected exactly one {_STEP_NAME!r} step, found {len(steps)}"
    assert "pytest" in str(steps[0].get("run", "")), "step must still run pytest"
    assert _masking_reasons(steps[0]) == [], (
        f"{_STEP_NAME!r} masks failures: {_masking_reasons(steps[0])}"
    )


_UNMASKED = """
jobs:
  backend:
    steps:
      - name: Run every test file
        run: |
          # comment mentioning || true, set +e and exit 0 is not code
          echo "exit 0 inside a string is not a command" && test -d tests
          pytest -v -rs tests/ --timeout=90
"""

_MASKED = {
    "continue-on-error": """
jobs:
  backend:
    steps:
      - name: Run every test file
        continue-on-error: true
        run: pytest -v tests/
""",
    "|| true": """
jobs:
  backend:
    steps:
      - name: Run every test file
        run: pytest -v tests/ || true
""",
    "set +e": """
jobs:
  backend:
    steps:
      - name: Run every test file
        run: |
          set +e
          pytest -v tests/
""",
    "--continue-on-collection-errors": """
jobs:
  backend:
    steps:
      - name: Run every test file
        run: pytest -v tests/ --continue-on-collection-errors
""",
    "; exit 0": """
jobs:
  backend:
    steps:
      - name: Run every test file
        run: pytest -v tests/ ;   exit 0
""",
    "|| exit 0": """
jobs:
  backend:
    steps:
      - name: Run every test file
        run: pytest -v tests/ ||exit  0
""",
    "newline exit 0": """
jobs:
  backend:
    steps:
      - name: Run every test file
        run: |
          pytest -v tests/
            exit 0
""",
    "newline || exit 0": """
jobs:
  backend:
    steps:
      - name: Run every test file
        run: |
          pytest -v tests/ \\
            || exit 0
""",
    "job continue-on-error": """
jobs:
  backend:
    continue-on-error: true
    steps:
      - name: Run every test file
        run: pytest -v tests/
""",
}


def test_step_lives_in_full_suite_job():
    workflow = yaml.safe_load(_CI.read_text(encoding="utf-8"))
    job = (workflow.get("jobs") or {}).get(_JOB_ID)
    assert job is not None, f"job {_JOB_ID!r} missing from ci.yml"
    names = [s.get("name") for s in job.get("steps") or []]
    assert names.count(_STEP_NAME) == 1, (
        f"{_STEP_NAME!r} must be exactly once in job {_JOB_ID!r}"
    )
    assert _find_steps(workflow, _STEP_NAME) == [
        s for s in job["steps"] if s.get("name") == _STEP_NAME
    ], f"{_STEP_NAME!r} must not appear outside job {_JOB_ID!r}"


def test_checker_passes_unmasked_sample():
    steps = _find_steps(yaml.safe_load(_UNMASKED), _STEP_NAME)
    assert len(steps) == 1 and _masking_reasons(steps[0]) == []


@pytest.mark.parametrize("form", sorted(_MASKED))
def test_checker_fails_each_masked_sample(form):
    steps = _find_steps(yaml.safe_load(_MASKED[form]), _STEP_NAME)
    assert len(steps) == 1
    assert _masking_reasons(steps[0]) != [], f"masking form {form!r} not detected"
