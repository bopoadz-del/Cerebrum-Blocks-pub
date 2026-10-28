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

# A pytest command: at the start of a logical line, optionally via python -m.
_PYTEST_CMD = re.compile(r"^[ \t]*(?:python3?[ \t]+-m[ \t]+)?pytest\b")
# pytest used as a condition: its status is consumed, not propagated.
_PYTEST_COND = re.compile(
    r"(?:^|[;&|(]|\bthen|\bdo)[ \t]*(?:if|while|until|!)[ \t]+"
    r"(?:python3?[ \t]+-m[ \t]+)?pytest\b",
    re.MULTILINE,
)
# The only "||" fallbacks that keep a failure a failure (ORDERS 1030Z):
# "exit <non-zero>" and a bare "exit" (which returns pytest's own status).
_OR_EXIT_NONZERO = re.compile(r"^[ \t]*exit(?:[ \t]+0*[1-9][0-9]*)?[ \t]*$")


def _logical_lines(code: str) -> list[str]:
    """Join backslash continuations; drop blank lines."""
    joined = re.sub(r"\\[ \t]*\n", " ", code)
    return [ln for ln in joined.splitlines() if ln.strip()]


def _pytest_exit_swallowed(code: str, shell: str) -> list[str]:
    """Ways the code after (or around) a pytest command discards its status."""
    reasons: list[str] = []
    if _PYTEST_COND.search(code):
        reasons.append("pytest as condition")
    lines = _logical_lines(code)
    idx = [i for i, ln in enumerate(lines) if _PYTEST_CMD.search(ln)]
    pipefail = "pipefail" in shell or re.search(r"\bset\s+-[a-z]*o\s+pipefail\b", code)
    for i in idx:
        line = lines[i]
        # ANY "||" fallback, unless it is exit with a non-zero (or no) code
        for alt in line.split("||")[1:]:
            first = re.split(r"[;&|]", alt, maxsplit=1)[0]
            if not _OR_EXIT_NONZERO.match(first):
                reasons.append("|| fallback")
                break
        head = line.split("||", 1)[0]
        if "|" in head and not pipefail:
            reasons.append("pipe without pipefail")
        if re.search(r";[ \t]*\S", head) or re.search(r"(?<!&)&(?!&)", head):
            reasons.append("command after pytest")
    if idx and idx[-1] != len(lines) - 1:
        reasons.append("command after pytest")
    return sorted(set(reasons))


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
    reasons.extend(_pytest_exit_swallowed(code, str(step.get("shell", ""))))
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
          python -m pip install pytest-timeout==2.4.0
          pytest -v -rs tests/ --timeout=90
"""

_ALLOWED = {
    "|| exit 1": """
jobs:
  backend:
    steps:
      - name: Run every test file
        run: |
          pytest -v -rs tests/ --timeout=90 \\
            -o faulthandler_timeout=75 --tb=short || exit 1
""",
    "bare || exit": """
jobs:
  backend:
    steps:
      - name: Run every test file
        run: pytest -v tests/ || exit
""",
    "tee with pipefail shell": """
jobs:
  backend:
    steps:
      - name: Run every test file
        shell: bash --noprofile --norc -eo pipefail {0}
        run: pytest -v tests/ | tee pytest.log
""",
}

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
    "|| echo failed": """
jobs:
  backend:
    steps:
      - name: Run every test file
        run: pytest -v tests/ || echo failed
""",
    "|| echo continued": """
jobs:
  backend:
    steps:
      - name: Run every test file
        run: |
          pytest -v tests/ \\
            || echo "tests failed"
""",
    "|| echo then || exit 1": """
jobs:
  backend:
    steps:
      - name: Run every test file
        run: pytest -v tests/ || echo x || exit 1
""",
    "||: no space": """
jobs:
  backend:
    steps:
      - name: Run every test file
        run: "pytest -v tests/ ||:"
""",
    "|| :": """
jobs:
  backend:
    steps:
      - name: Run every test file
        run: "pytest -v tests/ || :"
""",
    "; true": """
jobs:
  backend:
    steps:
      - name: Run every test file
        run: pytest -v tests/ ; true
""",
    "; echo": """
jobs:
  backend:
    steps:
      - name: Run every test file
        run: pytest -v tests/; echo done
""",
    "& background": """
jobs:
  backend:
    steps:
      - name: Run every test file
        run: pytest -v tests/ &
""",
    "trailing true line": """
jobs:
  backend:
    steps:
      - name: Run every test file
        run: |
          pytest -v tests/
          true
""",
    "trailing echo line": """
jobs:
  backend:
    steps:
      - name: Run every test file
        run: |
          python -m pytest -v tests/
          echo finished
""",
    "pipe to tee": """
jobs:
  backend:
    steps:
      - name: Run every test file
        run: pytest -v tests/ | tee pytest.log
""",
    "if/then wrapper": """
jobs:
  backend:
    steps:
      - name: Run every test file
        run: |
          if pytest -v tests/; then echo ok; fi
""",
    "if/else wrapper": """
jobs:
  backend:
    steps:
      - name: Run every test file
        run: |
          if python -m pytest -v tests/; then
            echo ok
          else
            echo failed
          fi
""",
    "! pytest": """
jobs:
  backend:
    steps:
      - name: Run every test file
        run: '! pytest -v tests/'
""",
    "until pytest": """
jobs:
  backend:
    steps:
      - name: Run every test file
        run: until pytest -v tests/; do break; done
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


@pytest.mark.parametrize("form", sorted(_ALLOWED))
def test_checker_passes_each_allowed_sample(form):
    steps = _find_steps(yaml.safe_load(_ALLOWED[form]), _STEP_NAME)
    assert len(steps) == 1
    assert _masking_reasons(steps[0]) == [], f"{form!r} keeps the failure but was flagged"


@pytest.mark.parametrize("form", sorted(_MASKED))
def test_checker_fails_each_masked_sample(form):
    steps = _find_steps(yaml.safe_load(_MASKED[form]), _STEP_NAME)
    assert len(steps) == 1
    assert _masking_reasons(steps[0]) != [], f"masking form {form!r} not detected"
