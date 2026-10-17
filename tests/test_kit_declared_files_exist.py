"""Every file a kit manifest declares is authored somewhere.

``publish_kit`` mirrors each declared artifact from the kit root (kit-owned
content) or the repo root (shared platform code). A declaration that
resolves to neither cannot be republished, so the kit's ``bundle/`` silently
becomes the only, frozen copy. Checked for every kit on disk; none is named.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
KITS_DIR = REPO / "block_store" / "kits"


def _publish_kit():
    spec = importlib.util.spec_from_file_location("publish_kit", REPO / "scripts" / "publish_kit.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


KITS = sorted(p.parent.name for p in KITS_DIR.glob("*/manifest.json") if not p.parent.name.startswith("_"))


@pytest.mark.parametrize("kit_id", KITS)
def test_every_declared_artifact_resolves_to_an_authored_source(kit_id: str):
    kit_dir = KITS_DIR / kit_id
    manifest = json.loads((kit_dir / "manifest.json").read_text(encoding="utf-8"))
    resolve = _publish_kit().resolve_source
    unresolved = [
        item["src"] for item in manifest.get("artifacts") or []
        if resolve(kit_dir, item["src"]) is None
    ]
    assert not unresolved, f"{kit_id} declares files authored nowhere: {unresolved}"


def test_an_undeclarable_artifact_is_caught(tmp_path):
    """Control: a declaration that resolves nowhere is refused."""
    assert _publish_kit().resolve_source(tmp_path, "app/zorblat/never_written.py") is None
