"""Registry-only blocks must carry their signed manifest's capability policy.

New-shape tests for the PRR finding: ``_BLOCK_CAPS`` is built only over
registered defs, so a block that exists in ``block_registry/`` but not in
``BLOCK_REGISTRY`` (the common case on a virgin boot — roughly 70 of 108)
got default-empty capabilities: manifest ``permissions`` never consulted,
community fail-closed tier never applied, ``must_run_out_of_process`` always
False — every such block ran as an unsandboxed local subprocess regardless
of policy. Capabilities now resolve from the signed manifest with the same
fail-closed tier as registered blocks.
"""

from __future__ import annotations

import json

import pytest

from app import blocks as blocks_mod
from app.blocks import get_block_capabilities
from app.core.block_capabilities import BlockCapabilities


def _registry_only_names():
    root = blocks_mod._REGISTRY_ROOT
    return sorted(
        d.name
        for d in root.iterdir()
        if d.is_dir()
        and (d / "block.json").exists()
        and d.name not in blocks_mod._BLOCK_DEFS
    )


def test_registry_only_blocks_exist_and_get_a_tier():
    names = _registry_only_names()
    assert names, "expected registry-only blocks (virgin boot registers ~32 of 108)"
    caps = get_block_capabilities(names[0])
    assert caps.publisher_tier is not None, (
        "registry-only block resolved to default capabilities — the policy "
        "bypass is back"
    )


def test_platform_signed_registry_block_stays_in_process():
    """The live store must not break: certified platform blocks keep the
    in-process/subprocess path exactly as before this fix."""
    for name in _registry_only_names():
        manifest = json.loads(
            (blocks_mod._REGISTRY_ROOT / name / "block.json").read_text(
                encoding="utf-8"
            )
        )
        if manifest.get("publisher_id") == "cerebrum_platform":
            caps = get_block_capabilities(name)
            assert caps.publisher_tier == "certified"
            assert caps.must_run_out_of_process is False
            return
    pytest.skip("no platform-signed registry-only block found")


def test_unknown_publisher_fails_closed_to_community(monkeypatch, tmp_path):
    shady = tmp_path / "shady_block"
    shady.mkdir()
    (shady / "block.json").write_text(
        json.dumps(
            {
                "name": "shady_block",
                "publisher_id": "totally_unknown_publisher",
                "permissions": {"network": True, "imports": ["subprocess"]},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(blocks_mod, "_REGISTRY_ROOT", tmp_path)
    monkeypatch.setattr(blocks_mod, "_REGISTRY_ONLY_CAPS", {})

    caps = get_block_capabilities("shady_block")

    # Fail-closed tier + manifest permissions actually consulted.
    assert caps.publisher_tier == "community"
    assert caps.must_run_out_of_process is True
    assert caps.has_network is True
    assert "subprocess" in caps.privileged_imports


def test_unknown_name_still_defaults(monkeypatch, tmp_path):
    monkeypatch.setattr(blocks_mod, "_REGISTRY_ROOT", tmp_path)
    monkeypatch.setattr(blocks_mod, "_REGISTRY_ONLY_CAPS", {})
    caps = get_block_capabilities("no_such_block_anywhere")
    assert caps == BlockCapabilities()


def test_resolution_is_cached(monkeypatch, tmp_path):
    shady = tmp_path / "cached_block"
    shady.mkdir()
    (shady / "block.json").write_text(
        json.dumps({"name": "cached_block", "publisher_id": "x", "permissions": {}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(blocks_mod, "_REGISTRY_ROOT", tmp_path)
    cache: dict = {}
    monkeypatch.setattr(blocks_mod, "_REGISTRY_ONLY_CAPS", cache)

    first = get_block_capabilities("cached_block")
    assert "cached_block" in cache
    assert get_block_capabilities("cached_block") is first
