"""Item A: only the kits that mirror a re-signed block get their bundle
refreshed, and which kits those are is read from the manifests -- never a
hardcoded kit name.

Everything runs against a throwaway tmp repo; no real kit, key, or registry
file is touched.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "refresh_kit_bundles", ROOT / "scripts" / "refresh_kit_bundles.py"
)
rkb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rkb)


def _kit(kits_root: Path, kit_id: str, srcs, status="available"):
    d = kits_root / kit_id
    d.mkdir(parents=True)
    manifest = {
        "id": kit_id,
        "status": status,
        "artifacts": [{"src": s, "dest": s} for s in srcs],
    }
    (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return d


def _two_kit_repo(tmp_path: Path):
    """One kit mirrors a block.json, the other mirrors only an app file."""
    root = tmp_path / "repo"
    kits = root / "block_store" / "kits"
    kits.mkdir(parents=True)
    _kit(kits, "mirrors_block", ["app/core/x.py", "block_registry/alpha/block.json"])
    _kit(kits, "mirrors_nothing", ["app/core/y.py", "block_registry/beta/block.json"])
    return root, kits


RESIGNED = ["block_registry/alpha/block.json"]  # only alpha was re-signed


def test_only_kits_that_mirror_a_resigned_block_are_selected(tmp_path):
    """Two inputs, two results: the alpha-mirroring kit is in, the other is out."""
    root, kits = _two_kit_repo(tmp_path)
    selected = rkb.affected_kits(kits, RESIGNED)
    assert selected == ["mirrors_block"]
    assert "mirrors_nothing" in [p.name for p in kits.iterdir()]  # it exists, just not chosen


def test_refresh_mirrors_only_the_affected_kit(tmp_path):
    """refresh() runs the mirror for the affected kit and only that one."""
    root, _ = _two_kit_repo(tmp_path)
    called: list[str] = []
    refreshed = rkb.refresh(root, RESIGNED, mirror=lambda kit, r: called.append(kit))
    assert refreshed == ["mirrors_block"]
    assert called == ["mirrors_block"]  # the non-mirroring kit is never touched


def test_no_resigned_blocks_refreshes_nothing(tmp_path):
    root, _ = _two_kit_repo(tmp_path)
    called: list[str] = []
    assert rkb.refresh(root, [], mirror=lambda kit, r: called.append(kit)) == []
    assert called == []


def test_in_development_kit_is_not_refreshed(tmp_path):
    """Only ``available`` kits are freshness-checked, so only those are mirrored."""
    root = tmp_path / "repo"
    kits = root / "block_store" / "kits"
    kits.mkdir(parents=True)
    _kit(kits, "dev_kit", ["block_registry/alpha/block.json"], status="in_development")
    assert rkb.affected_kits(kits, RESIGNED) == []


def test_selection_has_no_hardcoded_kit_name():
    src = (ROOT / "scripts" / "refresh_kit_bundles.py").read_text(encoding="utf-8")
    for kit_name in ("finance_ops", "automotive", "finance\"", "'finance"):
        assert kit_name not in src, f"kit name {kit_name!r} must not be hardcoded"


# ---- G2 post-hoc mutants A6 / A7 / A9 (workflow entry path + mirror failure) ---

import subprocess
import sys

import pytest


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=str(root), check=True, capture_output=True,
    )


def _git_repo_with_blocks(tmp_path: Path) -> Path:
    """A committed tmp git repo with two block.json files and one non-block file."""
    root = tmp_path / "gitrepo"
    for name in ("alpha", "beta"):
        d = root / "block_registry" / name
        d.mkdir(parents=True)
        (d / "block.json").write_text(json.dumps({"id": name}), encoding="utf-8")
        (d / "block.py").write_text("X = 1\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


def _touch_signature(root: Path, name: str) -> None:
    p = root / "block_registry" / name / "block.json"
    m = json.loads(p.read_text(encoding="utf-8"))
    m["signature"] = f"sig-{name}"
    p.write_text(json.dumps(m), encoding="utf-8")


@pytest.mark.parametrize("changed", ["alpha", "beta"])
def test_git_diff_detection_returns_exactly_the_resigned_block_json(tmp_path, changed):
    """A6: two inputs, two results -- the changed block.json is reported, and
    a changed non-manifest file under block_registry is not."""
    root = _git_repo_with_blocks(tmp_path)
    _touch_signature(root, changed)
    (root / "block_registry" / "alpha" / "block.py").write_text("X = 2\n", encoding="utf-8")
    assert rkb._changed_block_manifests(root) == [f"block_registry/{changed}/block.json"]


def test_git_diff_detection_clean_tree_returns_nothing(tmp_path):
    root = _git_repo_with_blocks(tmp_path)
    assert rkb._changed_block_manifests(root) == []


@pytest.mark.parametrize("paths", [
    ["block_registry/alpha/block.json"],
    ["block_registry/beta/block.json", "block_registry/alpha/block.json"],
])
def test_main_forwards_explicit_paths_to_refresh(tmp_path, monkeypatch, paths):
    """A7: main() hands its re-signed paths to refresh() unchanged."""
    seen: list[list[str]] = []
    monkeypatch.setattr(rkb, "refresh", lambda root, resigned: seen.append(list(resigned)) or [])
    assert rkb.main(list(paths), root=tmp_path) == 0
    assert seen == [paths]


@pytest.mark.parametrize("changed", ["alpha", "beta"])
def test_main_without_args_uses_git_diff_paths(tmp_path, monkeypatch, changed):
    """A6+A7 on the workflow entry path: no argv -> git diff -> refresh()."""
    root = _git_repo_with_blocks(tmp_path)
    _touch_signature(root, changed)
    seen: list[list[str]] = []
    monkeypatch.setattr(rkb, "refresh", lambda r, resigned: seen.append(list(resigned)) or [])
    assert rkb.main([], root=root) == 0
    assert seen == [[f"block_registry/{changed}/block.json"]]


def _fake_publish_kit(root: Path, exit_code: int) -> None:
    s = root / "scripts"
    s.mkdir(parents=True, exist_ok=True)
    (s / "publish_kit.py").write_text(
        "import sys\nsys.exit(%d)\n" % exit_code, encoding="utf-8"
    )


@pytest.mark.parametrize("code", [1, 3])
def test_failing_publish_kit_raises_not_swallowed(tmp_path, code):
    """A9: a non-zero publish_kit exit is a refusal, naming the kit and code."""
    _fake_publish_kit(tmp_path, code)
    with pytest.raises(RuntimeError) as exc:
        rkb._run_publish_kit("some_kit", tmp_path)
    assert "some_kit" in str(exc.value) and f"exit {code}" in str(exc.value)


def test_succeeding_publish_kit_does_not_raise(tmp_path):
    _fake_publish_kit(tmp_path, 0)
    assert rkb._run_publish_kit("some_kit", tmp_path) is None


@pytest.mark.parametrize("code", [1, 3])
def test_main_does_not_report_success_when_mirror_fails(tmp_path, code):
    """A9 end-to-end: a failing publish_kit for an affected kit makes main()
    fail (exception), so the workflow step goes red before the commit."""
    root = tmp_path / "repo"
    kits = root / "block_store" / "kits"
    kits.mkdir(parents=True)
    _kit(kits, "mirrors_block", ["block_registry/alpha/block.json"])
    _fake_publish_kit(root, code)
    with pytest.raises(RuntimeError, match=f"exit {code}"):
        rkb.main(["block_registry/alpha/block.json"], root=root)
