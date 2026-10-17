"""A pin change without a lock delta must fail. Mutation-tested.

The gate lives in ``scripts/check_lockfile_consistency.py``. These tests
apply synthetic diffs so the job cannot rot into a no-op that only ever
sees a clean tree.

Pairs are the ones that actually exist in this repository. Unpaired pin
files are listed so nobody invents a lock for them here.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "check_lockfile_consistency.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_lockfile_consistency", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gate = _load()


def _tree(tmp_path: Path) -> Path:
    """Minimal pin+lock tree the gate will accept as complete."""
    (tmp_path / "requirements.txt").write_text("fastapi==0.141.1\n", encoding="utf-8")
    (tmp_path / "requirements.lock").write_text("fastapi==0.141.1\n", encoding="utf-8")
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text('{"name":"x"}\n', encoding="utf-8")
    (frontend / "package-lock.json").write_text('{"name":"x"}\n', encoding="utf-8")
    return tmp_path


def test_declared_pairs_exist_and_unpaired_pins_have_no_lock():
    """Inventory, not invention: only real pairs are gated."""
    for pin, lock in gate.PAIRS:
        assert (REPO / pin).is_file(), f"declared pin missing: {pin}"
        assert (REPO / lock).is_file(), f"declared lock missing: {lock}"
    for pin in gate.UNPAIRED_PINS:
        assert (REPO / pin).is_file(), f"unpaired pin missing from tree: {pin}"
        # A sibling lock must not appear later and go ungated, and we
        # must not invent one in this PR.
        stem = Path(pin)
        invented = (
            stem.with_suffix(".lock"),
            stem.with_name("requirements.lock"),
            stem.with_name("package-lock.json"),
            stem.with_name("poetry.lock"),
            stem.with_name("uv.lock"),
        )
        for candidate in invented:
            assert not candidate.is_file(), (
                f"unpaired pin {pin} now has {candidate.relative_to(REPO)}; "
                "add it to PAIRS rather than leaving it silent"
            )


def test_pin_only_change_fails(tmp_path):
    root = _tree(tmp_path)
    code = gate.evaluate(root, {"requirements.txt"})
    assert code == 1
    code = gate.evaluate(root, {"frontend/package.json"})
    assert code == 1


def test_pin_and_lock_change_passes(tmp_path):
    root = _tree(tmp_path)
    assert gate.evaluate(root, {"requirements.txt", "requirements.lock"}) == 0
    assert (
        gate.evaluate(
            root, {"frontend/package.json", "frontend/package-lock.json"}
        )
        == 0
    )


def test_lock_only_change_passes(tmp_path):
    root = _tree(tmp_path)
    assert gate.evaluate(root, {"requirements.lock"}) == 0
    assert gate.evaluate(root, {"frontend/package-lock.json"}) == 0


def test_empty_delta_passes(tmp_path):
    assert gate.evaluate(_tree(tmp_path), set()) == 0


def test_missing_declared_lock_fails(tmp_path):
    (tmp_path / "requirements.txt").write_text("fastapi==0.141.1\n", encoding="utf-8")
    # No requirements.lock, and no frontend pair either.
    assert gate.evaluate(tmp_path, set()) == 1


def test_undetermined_changed_set_fails_closed(tmp_path):
    """No skip: if the checker cannot see a delta, it fails."""
    root = _tree(tmp_path)
    assert gate.evaluate(root, None) == 1
    assert gate.main(["--repo-root", str(root)], env={}) == 1


def test_cli_synthetic_pin_only_fails(tmp_path, capsys):
    root = _tree(tmp_path)
    assert (
        gate.main(
            ["--repo-root", str(root), "--changed", "requirements.txt"],
            env={},
        )
        == 1
    )
    err = capsys.readouterr().err
    assert "LOCKFILE_CONSISTENCY_FAIL" in err
    assert "requirements.txt" in err


def test_cli_synthetic_paired_change_passes(tmp_path):
    root = _tree(tmp_path)
    assert (
        gate.main(
            [
                "--repo-root",
                str(root),
                "--changed",
                "requirements.txt",
                "requirements.lock",
            ],
            env={},
        )
        == 0
    )


def test_unpaired_pin_is_not_gated(tmp_path):
    """Changing an unpaired pin is not a lock-delta failure."""
    root = _tree(tmp_path)
    assert gate.evaluate(root, {"sandbox-runner/requirements.txt"}) == 0
    assert "sandbox-runner/requirements.txt" not in {p for p, _ in gate.PAIRS}


def _job_body(workflow: str, job_id: str) -> str:
    marker = f"  {job_id}:"
    start = workflow.find(marker)
    assert start != -1, f"CI is missing required job {job_id}"
    rest = workflow[start + len(marker) :]
    end = len(rest)
    for i, line in enumerate(rest.splitlines()[1:], start=1):
        if line.startswith("  ") and not line.startswith("   ") and line.endswith(":"):
            end = sum(len(part) + 1 for part in rest.splitlines()[:i])
            break
    return rest[:end]


def test_ci_workflow_wires_the_gate_as_required():
    """Census: the job exists, runs the checker, and is not allowed to fail."""
    workflow = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    body = _job_body(workflow, "lockfile-consistency")
    assert "python scripts/check_lockfile_consistency.py" in body, (
        "CI must run the lockfile-consistency checker"
    )
    assert "tests/test_lockfile_consistency.py" in body, (
        "CI must mutation-test the gate; listing the file is how this "
        "repo decides a new test file actually runs"
    )
    assert "continue-on-error:" not in body, (
        "a job allowed to fail is a job nobody reads"
    )
    assert "allow_failure:" not in body, (
        "a job allowed to fail is a job nobody reads"
    )
