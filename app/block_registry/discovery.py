"""Discovery helpers for the plug-and-play block registry."""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from app.block_registry.normalize import registry_block_response

logger = logging.getLogger(__name__)

REGISTRY_ROOT = Path(__file__).parent.parent.parent / "block_registry"


def load_manifest(block_id: str) -> Optional[Dict]:
    """Load block.json for a given block ID."""
    manifest_path = REGISTRY_ROOT / block_id / "block.json"
    if not manifest_path.exists():
        return None
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Failed to load manifest for %s: %s", block_id, e)
        return None


def scan_registry() -> List[Dict]:
    """Scan block_registry/ and return all valid manifests."""
    manifests = []
    if not REGISTRY_ROOT.exists():
        return manifests

    for block_dir in REGISTRY_ROOT.iterdir():
        if not block_dir.is_dir():
            continue
        manifest = load_manifest(block_dir.name)
        if manifest is not None:
            manifests.append(manifest)

    return manifests


def list_registry_blocks() -> List[Dict]:
    """Return registry blocks formatted like the existing /blocks response items."""
    blocks = []
    for manifest in scan_registry():
        blocks.append(registry_block_response(manifest))
    return blocks


def registry_block_exists(block_name: str) -> bool:
    """Check if a block exists in the registry."""
    return (REGISTRY_ROOT / block_name / "block.json").exists()


def registry_reuse_lookup(block_id: str) -> dict:
    """Exact-id REUSE present? query for Factory STEP 0 inventory.

    ``block_id`` is matched against the on-disk registry folder name
    (the store id), not guessed from tags or descriptions. A hit returns
    the manifest including L2.2 brief-scope fields. A miss is a negative
    answer, not an HTTP-level defect -- callers treat ``present`` as the
    inventory bit.
    """
    if not block_id or "/" in block_id or "\\" in block_id or block_id in {".", ".."}:
        return {"present": False, "id": block_id, "reuse": False}

    # Exact folder-name match against the on-disk entries. A direct
    # path join would let case-insensitive filesystems (Windows/macOS)
    # resolve 'PDF' to 'pdf/' and turn the negative lookup into a guess.
    exact = next(
        (entry.name for entry in REGISTRY_ROOT.iterdir() if entry.name == block_id),
        None,
    )
    if exact is None:
        return {"present": False, "id": block_id, "reuse": False}

    manifest = load_manifest(exact)
    if manifest is None:
        return {"present": False, "id": block_id, "reuse": False}

    return {
        "present": True,
        "id": manifest.get("id", block_id),
        "reuse": True,
        "source": "registry",
        "reads": manifest.get("reads", []),
        "writes": manifest.get("writes", []),
        "never": manifest.get("never", []),
        "acceptance": manifest.get("acceptance", []),
        "manifest": manifest,
    }
