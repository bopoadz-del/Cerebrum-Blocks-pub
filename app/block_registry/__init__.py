"""Block registry module for plug-and-play block discovery and execution."""

from .discovery import (
    load_manifest,
    scan_registry,
    list_registry_blocks,
    registry_block_exists,
    registry_reuse_lookup,
)

__all__ = [
    "load_manifest",
    "scan_registry",
    "list_registry_blocks",
    "registry_block_exists",
    "registry_reuse_lookup",
]
