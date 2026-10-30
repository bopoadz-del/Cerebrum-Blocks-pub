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
# (d) the key-removal step comes after the sign step and before commit/push.
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


def push_step(steps: list[dict]) -> int:
    return _index(steps, lambda ln: ln.startswith("git push"))


def sign_step(steps: list[dict]) -> int:
    return _index(steps, lambda ln: "rotate_publisher_key.py" in ln)


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


def test_resign_key_rm_step_between_sign_and_commit_push():
    steps = _resign_steps()
    r, s, c, p = key_rm_step(steps), sign_step(steps), commit_step(steps), push_step(steps)
    assert r >= 0, "no step removes $KEY_FILE"
    assert s >= 0 and c >= 0 and p >= 0, "sign, commit and push steps must all exist"
    assert s < r, f"key-removal step (index {r}) must come after the sign step (index {s})"
    assert r < c and r < p, (
        f"key-removal step (index {r}) must come before commit (index {c}) and push (index {p})")


def test_resign_helpers_two_inputs_two_results():
    good = [
        {"run": 'echo "KEY_FILE=$RUNNER_TEMP/k.pem" >> "$GITHUB_ENV"'},
        {"run": 'umask 077\nprintf x > "$KEY_FILE"'},
        {"run": 'python scripts/rotate_publisher_key.py'},
        {"if": "always()", "run": 'rm -f "$KEY_FILE"'},
        {"run": 'git commit -m x\ngit push origin b'},
    ]
    bad = [
        {"run": 'echo "KEY_FILE=$GITHUB_WORKSPACE/k.pem" >> "$GITHUB_ENV"'},
        {"run": 'printf x > "$KEY_FILE"\numask 077'},
        {"run": 'python scripts/rotate_publisher_key.py'},
        {"run": 'git commit -m x\ngit push origin b'},
        {"run": 'rm -f "$KEY_FILE"'},
    ]
    assert (key_path_step(good), key_path_step(bad)) == (0, -1)
    assert (umask_before_write(good[1]), umask_before_write(bad[1])) == (True, False)
    assert (runs_always(good[3]), runs_always(bad[4])) == (True, False)
    assert (runs_always({"if": "${{ always() }}"}), runs_always({"if": "success()"})) == (True, False)
    assert (key_rm_step(good) < push_step(good), key_rm_step(bad) < push_step(bad)) == (True, False)
    assert (sign_step(good) < key_rm_step(good), sign_step(bad) < key_rm_step(bad)) == (True, True)
    assert key_path_step([{"run": 'echo "KEY_FILE=$RUNNER_TEMP/k.pem" >> "$GITHUB_OUTPUT"'}]) == -1


# --- ST-6d: actionlint.yml install is checksum-pinned and shellcheck stays on ---
# (a) no step's run/args disables an integration (-shellcheck= / -pyflakes=);
# (b) a run step pipes a pinned 64-hex sha256 into `sha256sum -c`, and that
#     value is the published checksum of the pinned release asset;
# (c) the file curl downloads is the file sha256sum checks and tar extracts,
#     and the lint step runs that extracted binary. No curl|bash.

ACTIONLINT = REPO / ".github" / "workflows" / "actionlint.yml"

# From each release's actionlint_<v>_checksums.txt (linux_amd64 tarball).
# Bumping the version means adding its published checksum here.
ACTIONLINT_RELEASE_SHA256 = {
    "1.7.12": "8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8",
}

_HEX64 = re.compile(r"[0-9a-f]{64}")


def _expand(text: str, env: dict) -> str:
    return re.sub(r"\$\{?(\w+)\}?", lambda m: str(env.get(m.group(1), m.group(0))), text)


def disabled_integrations(steps: list[dict]) -> list[str]:
    hits = []
    for step in steps:
        texts = [step.get("run")] + [v for v in (step.get("with") or {}).values()]
        for t in texts:
            if isinstance(t, str):
                hits += re.findall(r"-(?:shellcheck|pyflakes)=", t)
    return hits


def checksum_install(steps: list[dict]) -> dict | None:
    """Facts of the step that downloads, verifies and extracts actionlint, or None."""
    for step in steps:
        env = {k: str(v) for k, v in (step.get("env") or {}).items()}
        lines = _run_lines(step)
        local = {}
        for ln in lines:
            m = re.fullmatch(r"""(\w+)=["']?([^"'\s]+)["']?""", ln)
            if m:
                local[m.group(1)] = _expand(m.group(2), env)
        scope = {**env, **local}
        joined = _expand(" ".join(lines).replace("\\ ", " "), scope)
        check = re.search(r"""echo\s+["']?(\S+)\s+(\S+?)["']?\s*\|\s*sha256sum\s+-c(?:\s+-)?(?:\s|$)""", joined)
        if not check:
            continue
        dl = re.search(r"""curl\s[^|]*?-o\s+["']?(\S+?)["']?\s+["']?(https://\S+?)["']?(?:\s|$)""", joined)
        tar = re.search(r"""tar\s+-x\w*\s+["']?(\S+?)["']?\s""", joined)
        return {"sha": check.group(1), "checked": check.group(2),
                "downloaded": dl.group(1) if dl else None, "url": dl.group(2) if dl else "",
                "extracted": tar.group(1) if tar else None,
                "version": env.get("ACTIONLINT_VERSION", ""), "joined": joined}
    return None


def _actionlint_steps() -> list[dict]:
    return _steps(yaml.safe_load(ACTIONLINT.read_text(encoding="utf-8")), "actionlint")


def test_actionlint_integrations_not_disabled():
    assert disabled_integrations(_actionlint_steps()) == []


def test_actionlint_no_pipe_to_shell():
    for step in _actionlint_steps():
        run = step.get("run") or ""
        assert not re.search(r"\|\s*(ba)?sh\b|(ba)?sh\s+<\(", run), f"pipe-to-shell in: {run!r}"


def test_actionlint_install_checksum_pinned_to_release():
    facts = checksum_install(_actionlint_steps())
    assert facts is not None, "no run step pipes a pinned sha256 into `sha256sum -c`"
    assert _HEX64.fullmatch(facts["sha"]), f"not a 64-hex sha256: {facts['sha']!r}"
    assert facts["version"] in ACTIONLINT_RELEASE_SHA256, f"unknown pinned version {facts['version']!r}"
    assert facts["sha"] == ACTIONLINT_RELEASE_SHA256[facts["version"]]
    assert f"/v{facts['version']}/actionlint_{facts['version']}_linux_amd64.tar.gz" in facts["url"]


def test_actionlint_checked_file_is_the_downloaded_and_run_binary():
    steps = _actionlint_steps()
    facts = checksum_install(steps)
    assert facts is not None, "no checksum step"
    assert facts["downloaded"] and facts["downloaded"] == facts["checked"] == facts["extracted"], facts
    lint = [s for s in steps if "actionlint" in (s.get("run") or "") and "curl" not in (s.get("run") or "")]
    assert lint and all('"$RUNNER_TEMP/actionlint"' in s["run"] for s in lint), "lint must run the extracted binary"


def test_actionlint_helpers_two_inputs_two_results():
    good = {"env": {"V": "1"}, "run": 'f="a.tgz"\ncurl -sSfL -o "$RUNNER_TEMP/$f" \\\n  "https://x/v$V/$f"\n'
            'echo "' + "a" * 64 + '  $RUNNER_TEMP/$f" | sha256sum -c -\ntar -xzf "$RUNNER_TEMP/$f" -C d actionlint'}
    nocheck = {"run": good["run"].replace("sha256sum -c -", "sha256sum -")}
    assert checksum_install([good])["sha"] == "a" * 64 and checksum_install([nocheck]) is None
    assert checksum_install([good])["checked"] == checksum_install([good])["downloaded"]
    assert (disabled_integrations([{"run": "actionlint -shellcheck="}]),
            disabled_integrations([{"run": "actionlint"}])) == (["-shellcheck="], [])
    assert disabled_integrations([{"uses": "x", "with": {"args": "-pyflakes="}}]) == ["-pyflakes="]
