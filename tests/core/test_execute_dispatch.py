"""Tests for the execute-router capability dispatch logic."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.routers.execute import should_run_out_of_process, _run_block, ExecuteRequest


def test_core_blocks_run_in_process():
    """Core blocks default to safe capabilities and run in-process."""
    assert not should_run_out_of_process("chat")
    assert not should_run_out_of_process("pdf")


def test_safe_registry_blocks_run_in_process():
    """Registry blocks with no elevated capabilities run in-process."""
    assert not should_run_out_of_process("construction_v2")


def test_block_with_network_runs_out_of_process(tmp_path, monkeypatch):
    """A registry block declaring network access runs out-of-process."""
    import json
    from app.core.block_capabilities import BlockCapabilities

    registry_root = tmp_path / "block_registry"
    block_dir = registry_root / "net_block"
    block_dir.mkdir(parents=True)
    (block_dir / "block.json").write_text(
        json.dumps({
            "id": "net_block",
            "permissions": {"network": True, "filesystem": False, "imports": [], "blocks": []},
        })
    )
    caps = BlockCapabilities.from_registry("net_block", registry_root)
    assert caps.has_network
    assert not caps.is_safe_for_in_process


def test_block_with_filesystem_runs_out_of_process(tmp_path):
    """A registry block declaring filesystem access runs out-of-process."""
    import json
    from app.core.block_capabilities import BlockCapabilities

    registry_root = tmp_path / "block_registry"
    block_dir = registry_root / "fs_block"
    block_dir.mkdir(parents=True)
    (block_dir / "block.json").write_text(
        json.dumps({
            "id": "fs_block",
            "permissions": {"network": False, "filesystem": ["/tmp"], "imports": [], "blocks": []},
        })
    )
    caps = BlockCapabilities.from_registry("fs_block", registry_root)
    assert caps.has_filesystem
    assert not caps.is_safe_for_in_process


def test_block_with_privileged_import_runs_out_of_process(tmp_path):
    """A registry block declaring a privileged import runs out-of-process."""
    import json
    from app.core.block_capabilities import BlockCapabilities

    registry_root = tmp_path / "block_registry"
    block_dir = registry_root / "os_block"
    block_dir.mkdir(parents=True)
    (block_dir / "block.json").write_text(
        json.dumps({
            "id": "os_block",
            "permissions": {"network": False, "filesystem": False, "imports": ["os"], "blocks": []},
        })
    )
    caps = BlockCapabilities.from_registry("os_block", registry_root)
    assert "os" in caps.privileged_imports
    assert not caps.is_safe_for_in_process


def test_revoked_block_runs_out_of_process():
    """Revoked publishers are always forced out-of-process by tier policy."""
    from app.core.block_capabilities import BlockCapabilities

    with patch("app.routers.execute.get_block_capabilities") as mock_caps:
        mock_caps.return_value = BlockCapabilities(publisher_tier="revoked")
        assert should_run_out_of_process("revoked_block") is True


@pytest.mark.asyncio
async def test_revoked_block_rejected_before_dispatch():
    """Revoked blocks are rejected with HTTP 403 before any dispatch."""
    from app.core.block_capabilities import BlockCapabilities

    request = ExecuteRequest(block="revoked_block")
    with (
        patch("app.routers.execute.get_block_capabilities") as mock_caps,
        patch("app.routers.execute.registry_block_exists", return_value=True),
        patch("app.routers.execute.enforce_block_access"),
    ):
        mock_caps.return_value = BlockCapabilities(publisher_tier="revoked")
        with pytest.raises(HTTPException) as exc_info:
            await _run_block(request, auth={})
        assert exc_info.value.status_code == 403


def test_community_safe_block_runs_out_of_process():
    """Community-tier publishers are sandboxed even with safe capabilities."""
    from app.core.block_capabilities import BlockCapabilities

    with patch("app.routers.execute.get_block_capabilities") as mock_caps:
        mock_caps.return_value = BlockCapabilities(
            publisher_tier="community",
            network=False,
            filesystem=False,
            imports=[],
            blocks=[],
        )
        assert should_run_out_of_process("community_safe_block") is True


def test_reviewed_safe_block_runs_in_process():
    """Reviewed publishers with safe capabilities run in-process."""
    from app.core.block_capabilities import BlockCapabilities

    with patch("app.routers.execute.get_block_capabilities") as mock_caps:
        mock_caps.return_value = BlockCapabilities(
            publisher_tier="reviewed",
            network=False,
            filesystem=False,
            imports=[],
            blocks=[],
        )
        assert should_run_out_of_process("reviewed_safe_block") is False


def test_certified_unsafe_block_runs_in_process():
    """Certified publishers are never forced to sandbox, even with unsafe caps."""
    from app.core.block_capabilities import BlockCapabilities

    with patch("app.routers.execute.get_block_capabilities") as mock_caps:
        mock_caps.return_value = BlockCapabilities(
            publisher_tier="certified",
            network=True,
            filesystem=False,
            imports=[],
            blocks=[],
        )
        assert should_run_out_of_process("certified_unsafe_block") is False
