"""Domain kit runtime block registration is DERIVED from the kit manifests.

A kit declares its container and blocks in block_store/kits/<kit>/manifest.json.
The loader reads that declaration; it holds no kit table of its own. These
tests hold for every kit on disk -- none is named here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import app.blocks as blocks_mod
from app.core.domain_kit_loader import kit_spec_map

ROOT = Path(__file__).resolve().parents[2]
KITS = sorted(
    p.parent.name for p in (ROOT / "block_store" / "kits").glob("*/manifest.json")
    if not p.parent.name.startswith("_")
)


def _manifest(kit_id: str) -> dict:
    return json.loads((ROOT / "block_store" / "kits" / kit_id / "manifest.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("kit_id", KITS)
def test_every_declared_block_with_source_is_registered_for_its_kit(kit_id: str):
    """Each block the manifest declares is generic (always registered) or in
    the kit's derived specs -- unless no source names it, which the kit
    composition audit owns."""
    declared = _manifest(kit_id).get("blocks")
    if not isinstance(declared, list):
        pytest.skip(reason="manifest declares no block list")
    specs = {name for name, _m, _c in kit_spec_map().get(kit_id, [])}
    generic = set(blocks_mod._GENERIC_BLOCK_DEFS)
    blocks_dir = ROOT / "app" / "blocks"
    for block_id in declared:
        has_source = (blocks_dir / f"{block_id}.py").is_file() or (blocks_dir / block_id).is_dir()
        if block_id in generic or not has_source:
            continue
        assert block_id in specs, f"{kit_id} declares {block_id} but the loader does not register it"


@pytest.mark.parametrize("kit_id", KITS)
def test_a_declared_container_is_registered_under_the_kit_id(kit_id: str):
    container = (_manifest(kit_id).get("container") or {}).get("class") or ""
    if "." not in container:
        pytest.skip(reason="kit declares no container")
    module, cls = container.rsplit(".", 1)
    source = ROOT.joinpath(*module.split("."))
    if not (source.with_suffix(".py").is_file() or (source / "__init__.py").is_file()):
        pytest.skip(reason="declared container has no source")
    assert (kit_id, module, cls) in kit_spec_map()[kit_id]


def test_no_spec_names_a_module_nobody_wrote():
    """The old hand table listed connectors that were never written."""
    for kit_id, specs in kit_spec_map().items():
        for name, module, _cls in specs:
            base = ROOT.joinpath(*module.split("."))
            assert base.with_suffix(".py").is_file() or (base / "__init__.py").is_file(), (kit_id, name)
