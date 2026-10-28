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
