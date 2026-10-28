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
          # comment mentioning || true and set +e is not code
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
    "job continue-on-error": """
jobs:
  backend:
    continue-on-error: true
    steps:
      - name: Run every test file
        run: pytest -v tests/
""",
}


def test_checker_passes_unmasked_sample():
    steps = _find_steps(yaml.safe_load(_UNMASKED), _STEP_NAME)
    assert len(steps) == 1 and _masking_reasons(steps[0]) == []


@pytest.mark.parametrize("form", sorted(_MASKED))
def test_checker_fails_each_masked_sample(form):
    steps = _find_steps(yaml.safe_load(_MASKED[form]), _STEP_NAME)
    assert len(steps) == 1
    assert _masking_reasons(steps[0]) != [], f"masking form {form!r} not detected"
