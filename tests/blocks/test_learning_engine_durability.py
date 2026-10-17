"""The learning store must be durable, and the block must not choose the path.

The original defect was a default that pointed at /tmp: accumulated
corrections reset on every deploy. KERNEL_DEFAULTS 1.5 restates the
same durability property without a file path inside the block: the
platform injects a backend, and a backend the caller pointed at a
mounted disk still survives a reload.

These four tests keep that property. They no longer assert on a
module-level ``_STORAGE_PATH`` because that path is the thing the
contract forbids.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.blocks.learning_engine import LearningEngineBlock
from app.core.learning_store import FileLearningStore, MemoryLearningStore


def test_default_lands_on_memory_not_tmp():
    """Unconfigured, the block does not write a file — least of all /tmp."""
    block = LearningEngineBlock()
    assert isinstance(block._store, MemoryLearningStore)
    assert not hasattr(block, "_STORAGE_PATH")
    assert "storage_path" not in block.default_config


def test_explicit_override_still_wins(tmp_path):
    """An injected backend is the one that is used. Same claim as before:
    the caller-named store wins over any default."""
    target = tmp_path / "elsewhere" / "store.json"
    backend = FileLearningStore(str(target))
    block = LearningEngineBlock(config={"storage_backend": backend})

    assert block._store is backend
    block._state["formulas"]["demo"] = {"executions": 1}
    block._save_state()
    assert target.is_file()


def test_follows_the_path_it_was_handed(tmp_path):
    """Durability comes from the path the platform named (DATA_DIR, a
    mount), so the injected file store must track that path."""
    data_dir = tmp_path / "app" / "data"
    backend = FileLearningStore(str(data_dir / "learning_engine.json"))
    block = LearningEngineBlock(config={"storage_backend": backend})
    block._state["formulas"]["demo"] = {"executions": 7}
    block._save_state()

    assert (data_dir / "learning_engine.json").is_file()
    assert str(backend.path).startswith(str(data_dir))


def test_state_written_there_survives_a_reload(tmp_path):
    """Round trip: what is written must still be readable by a fresh block."""
    target = tmp_path / "learning_engine.json"
    first = LearningEngineBlock(config={"storage_backend": FileLearningStore(str(target))})
    first._state["formulas"]["demo"] = {"executions": 42}
    first._save_state()

    reloaded = LearningEngineBlock(
        config={"storage_backend": FileLearningStore(str(target))}
    )
    assert reloaded._state["formulas"]["demo"]["executions"] == 42


def test_this_module_does_not_reach_for_the_environment_or_a_file_path():
    """No ``os.getenv``, no ``os.environ``, no leftover ``_STORAGE_PATH``."""
    import app.blocks.learning_engine as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    reaches = [
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "os"
        and node.attr in ("getenv", "environ")
    ]
    assert reaches == [], "block code reached for the environment: %s" % reaches
    assert "_STORAGE_PATH" not in source
    assert "storage_path" not in module.LearningEngineBlock.default_config
