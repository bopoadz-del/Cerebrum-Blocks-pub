"""Capability model for block permissions (Track B Phase 4).

Parses a block manifest ``permissions`` dict into a structured capability
object and decides whether a block is safe to run in-process.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


# Imports that are forbidden by the static validator unless explicitly declared.
# Blocks declaring any of these need out-of-process execution.
PRIVILEGED_MODULES: Set[str] = {
    "os",
    "subprocess",
    "socket",
    "requests",
    "urllib",
    "pickle",
    "ctypes",
    "sys",
    "importlib",
}


@dataclass(frozen=True)
class BlockCapabilities:
    """Runtime capabilities declared by a block manifest."""

    network: bool = False
    filesystem: bool | List[str] = False
    imports: List[str] = field(default_factory=list)
    blocks: List[str] = field(default_factory=list)
    publisher_tier: Optional[str] = None

    @property
    def has_network(self) -> bool:
        """Return True if the block is allowed network access."""
        return bool(self.network)

    @property
    def has_filesystem(self) -> bool:
        """Return True if the block is allowed filesystem access."""
        return bool(self.filesystem)

    @property
    def privileged_imports(self) -> List[str]:
        """Return declared imports that require elevated capabilities."""
        return [imp for imp in self.imports if imp.split(".")[0] in PRIVILEGED_MODULES]

    @property
    def is_safe_for_in_process(self) -> bool:
        """Return True when the block can run inside the main API process.

        A block is considered safe only when it declares no network access, no
        filesystem access, no privileged imports, and no cross-block access.
        """
        if self.has_network or self.has_filesystem:
            return False
        if self.privileged_imports:
            return False
        if self.blocks:
            return False
        return True

    @property
    def must_run_out_of_process(self) -> bool:
        """Return True when this block must run outside the main process.

        Tiers override capability declarations:
          - community / revoked: always sandboxed
          - reviewed: capability-based (safe = in-process, unsafe = sandbox)
          - certified: pilot-proven; never forced to sandbox
          - unknown / None: capability-based, but unknown non-core blocks are
            resolved to "community" at load time
        """
        if self.publisher_tier in ("community", "revoked"):
            return True
        if self.publisher_tier == "certified":
            return False
        if self.publisher_tier == "reviewed":
            return not self.is_safe_for_in_process
        return not self.is_safe_for_in_process

    def allows_block_access(self, name: str) -> bool:
        """Return True if the block is permitted to access another block."""
        return name in self.blocks

    @classmethod
    def from_manifest(cls, manifest: Dict[str, Any]) -> "BlockCapabilities":
        """Parse capabilities from a block manifest.

        ``publisher_tier`` is NOT read from the manifest; it is a platform
        assertion set by ``app.blocks`` after consulting the publisher registry
        and certification store.
        """
        permissions = manifest.get("permissions") or {}
        network = bool(permissions.get("network", False))
        filesystem = permissions.get("filesystem", False)
        if filesystem is not False and not isinstance(filesystem, (bool, list)):
            filesystem = False
        imports = permissions.get("imports", []) or []
        blocks = permissions.get("blocks", []) or []
        return cls(
            network=network,
            filesystem=filesystem,
            imports=list(imports),
            blocks=list(blocks),
        )

    @classmethod
    def from_registry(cls, block_name: str, registry_root: Path | None = None) -> "BlockCapabilities":
        """Load capabilities from ``block_registry/<name>/block.json``.

        Returns a default (safe) capability object if the manifest is missing
        or unreadable.
        """
        if registry_root is None:
            registry_root = Path(__file__).resolve().parents[2] / "block_registry"
        manifest_path = registry_root / block_name / "block.json"
        if not manifest_path.exists():
            return cls()
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return cls()
        return cls.from_manifest(manifest)
