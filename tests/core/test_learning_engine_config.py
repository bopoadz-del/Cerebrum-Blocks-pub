"""learning_engine config contract: injected storage, kit default off.

The block does not choose a file path. Every kit ships with the engine
off. Training eligibility is independently labeled only — that pin lives
on the manifest and is asserted in test_manifest_contract.py.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

from app.blocks.learning_engine import LearningEngineBlock
from app.core.learning_store import FileLearningStore, MemoryLearningStore
from app.core.manifest_contract import TRAINING_ELIGIBILITY_POLICY

ROOT = Path(__file__).resolve().parents[2]
KITS = ROOT / "block_store" / "kits"


def test_storage_backend_is_injected_not_looked_up(tmp_path):
    backend = FileLearningStore(str(tmp_path / "state.json"))
    block = LearningEngineBlock(config={"storage_backend": backend})
    assert block._store is backend
    assert not isinstance(block._store, MemoryLearningStore) or backend is block._store


def test_unconfigured_block_uses_memory_and_says_so():
    block = LearningEngineBlock()
    assert isinstance(block._store, MemoryLearningStore)


def test_the_block_does_not_name_a_local_file_path():
    import app.blocks.learning_engine as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    reaches = [
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "os"
        and node.attr in ("getenv", "environ")
    ]
    assert reaches == []
    assert "storage_path" not in LearningEngineBlock.default_config
    text = Path(module.__file__).read_text(encoding="utf-8")
    assert "/tmp" not in text
    assert "DATA_DIR" not in text
    assert "LEARNING_ENGINE_STORAGE" not in text


def test_every_kit_defaults_learning_engine_off():
    found = []
    for manifest_path in sorted(KITS.glob("*/manifest.json")):
        if manifest_path.parent.name.startswith("_"):
            # Template is not strict JSON; check the text.
            text = manifest_path.read_text(encoding="utf-8")
            assert '"learning_engine_enabled": false' in text, manifest_path
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        found.append(manifest_path.parent.name)
        assert manifest.get("learning_engine_enabled") is False, (
            "%s must default learning_engine off" % manifest_path.parent.name
        )
    assert found, "no kits were checked"


def test_training_eligibility_pin_is_independently_labeled_only():
    assert TRAINING_ELIGIBILITY_POLICY == "independently_labeled_only"
