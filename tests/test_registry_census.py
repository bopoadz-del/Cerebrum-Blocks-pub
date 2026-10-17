"""B04 — the Store is honest about what it advertises.

Every ``block_registry/<id>/block.json`` is a public claim. The census
resolves that claim to a module that imports, an entrypoint that exists,
and identity metadata (id / name / version / description). It fails on
the first advertised block that does not, so a green run cannot hide a
second lie behind a collected list nobody reads.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "census_registry.py"
CI = REPO / ".github" / "workflows" / "ci.yml"
REGISTRY = REPO / "block_registry"


def _load():
    spec = importlib.util.spec_from_file_location("census_registry", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["census_registry"] = mod
    spec.loader.exec_module(mod)
    return mod


census = _load()


def _run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=cwd or REPO,
        capture_output=True,
        text=True,
        check=False,
    )


def _plant(root: Path, name: str, *, manifest: dict | None = None, module_ok: bool = True) -> Path:
    block = root / name
    block.mkdir(parents=True, exist_ok=True)
    body = {
        "id": name,
        "name": name.replace("_", " ").title(),
        "version": "1.0.0",
        "description": f"{name} planted block",
    }
    if manifest is not None:
        body.update(manifest)
    (block / "block.json").write_text(json.dumps(body), encoding="utf-8")
    if module_ok:
        # A planted module is not required: the live resolver looks at
        # app.blocks.<name>. module_ok=False is the missing-module case.
        pass
    return block


# -- the gate itself -------------------------------------------------------


def test_the_shelf_is_not_empty():
    advertised = census.advertised_blocks()
    assert len(advertised) >= 80, (
        f"census matched only {len(advertised)} advertised blocks — "
        "a selector that finds nothing is a skip"
    )


def test_census_is_zero_missing():
    """The Store launch path. First advertised block that does not resolve fails."""
    finding = census.first_missing()
    assert finding is None, (
        f"first advertised block that does not resolve: {finding}"
    )


def test_census_fails_on_the_first_block_not_the_second(tmp_path, monkeypatch):
    """A collected-all report can hide the first lie. This gate names it."""
    _plant(tmp_path, "alpha")
    _plant(tmp_path, "beta")
    _plant(tmp_path, "zeta")

    def _inspect(block_dir: Path):
        if block_dir.name == "beta":
            return census.Finding("beta", "planted missing module")
        if block_dir.name == "zeta":
            return census.Finding("zeta", "should not be reached as the first")
        return None

    monkeypatch.setattr(census, "inspect_block", _inspect)
    first = census.first_missing(tmp_path)
    assert first is not None
    assert first.block == "beta"
    assert "zeta" not in first.reason


def test_a_planted_missing_module_is_the_first_finding(tmp_path):
    """alpha is a real advertised name that resolves; planted_missing does not."""
    real = next(p for p in census.advertised_blocks() if p.name == "chat")
    planted = tmp_path / "block_registry"
    chat = planted / "chat"
    chat.mkdir(parents=True)
    (chat / "block.json").write_bytes((real / "block.json").read_bytes())
    _plant(
        planted,
        "zzz_planted_missing",
        manifest={
            "id": "zzz_planted_missing",
            "name": "Planted",
            "version": "0.0.0",
            "description": "must fail",
        },
    )
    first = census.first_missing(planted)
    assert first is not None
    assert first.block == "zzz_planted_missing"
    assert "failed to import" in first.reason or "no entrypoint" in first.reason


def test_missing_identity_metadata_fails_before_import(tmp_path):
    _plant(tmp_path, "no_ver", manifest={"version": ""})
    first = census.first_missing(tmp_path)
    assert first is not None
    assert first.block == "no_ver"
    assert "version" in first.reason


def test_id_must_match_the_folder(tmp_path):
    _plant(tmp_path, "folder_name", manifest={"id": "other_name"})
    first = census.first_missing(tmp_path)
    assert first is not None
    assert first.block == "folder_name"
    assert "does not match folder" in first.reason


def test_cli_exits_1_on_the_first_missing(tmp_path):
    _plant(tmp_path, "ghost")
    proc = _run("--root", str(tmp_path))
    assert proc.returncode == 1, proc.stdout
    assert "ghost" in proc.stdout


def test_cli_exits_0_when_the_live_shelf_is_honest():
    proc = _run()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "0 missing" in proc.stdout


# -- CI wiring -------------------------------------------------------------


def test_ci_runs_the_census_and_does_not_allow_it_to_fail():
    workflow = CI.read_text(encoding="utf-8")
    assert "python scripts/census_registry.py" in workflow
    assert "tests/test_registry_census.py" in workflow
    # The census step itself must not be the report-only hatch.
    backend = workflow.split("full-suite:", 1)[0]
    census_idx = backend.find("census_registry.py")
    assert census_idx != -1
    window = backend[max(0, census_idx - 400) : census_idx]
    assert "continue-on-error: true" not in window
