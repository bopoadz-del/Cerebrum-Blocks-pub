"""Tests for the fail-closed capability validation gate on kit-loaded blocks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.blocks import _REGISTRY_ROOT, _validate_block_capabilities


def test_kit_block_with_declared_permissions_passes(tmp_path: Path, monkeypatch):
    """A kit block with a parseable permissions declaration is admitted."""
    monkeypatch.setattr("app.blocks._REGISTRY_ROOT", tmp_path)
    block_dir = tmp_path / "kit_block"
    block_dir.mkdir()
    (block_dir / "block.json").write_text(
        json.dumps(
            {
                "id": "kit_block",
                "permissions": {
                    "network": False,
                    "filesystem": True,
                    "imports": ["os"],
                    "blocks": [],
                },
            }
        ),
        encoding="utf-8",
    )

    ok, reason = _validate_block_capabilities("kit_block")
    assert ok is True
    assert reason == ""


def test_kit_block_without_declaration_is_excluded(tmp_path: Path, monkeypatch):
    """A kit block with no block.json is excluded with a clear reason."""
    monkeypatch.setattr("app.blocks._REGISTRY_ROOT", tmp_path)

    ok, reason = _validate_block_capabilities("undeclared_block")
    assert ok is False
    assert "undeclared_block" in reason
    assert "no block.json declaration" in reason


def test_kit_block_with_invalid_permissions_is_excluded(tmp_path: Path, monkeypatch):
    """A malformed permissions declaration is treated as undeclared."""
    monkeypatch.setattr("app.blocks._REGISTRY_ROOT", tmp_path)
    block_dir = tmp_path / "bad_block"
    block_dir.mkdir()
    (block_dir / "block.json").write_text(
        json.dumps({"id": "bad_block", "permissions": "not-a-dict"}),
        encoding="utf-8",
    )

    ok, reason = _validate_block_capabilities("bad_block")
    assert ok is False
    assert "bad_block" in reason
    assert "permissions declaration missing or invalid" in reason


@pytest.mark.parametrize(
    "block_name",
    [
        "construction",
        "construction_advisor",
        "formula_executor_v2",
        "project_reasoner",
    ],
)
def test_construction_kit_blocks_have_declarations(block_name: str):
    """Construction kit blocks that previously loaded unvalidated now have declarations."""
    manifest_path = _REGISTRY_ROOT / block_name / "block.json"
    assert manifest_path.exists(), f"missing declaration for {block_name}"
    ok, reason = _validate_block_capabilities(block_name)
    assert ok is True, reason


def test_legacy_extended_block_without_declaration_is_admitted():
    """Legacy extended blocks (e.g. drive adapters) load without a declaration.

    The fail-closed capability gate targets kit-loaded blocks only. Legacy
    _EXTENDED_BLOCK_DEFS blocks retain their pre-gate behavior so existing
    integrations keep working while the kit path is hardened.
    """
    from app.blocks import _BLOCK_DEFS

    for name in ("local_drive", "google_drive", "onedrive", "android_drive"):
        assert name in _BLOCK_DEFS, f"legacy block '{name}' was excluded"
