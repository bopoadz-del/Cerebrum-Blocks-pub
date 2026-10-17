"""Neutral provenance verification: file digests and manifest root hashes."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Set


class ProvenanceMismatch(Exception):
    """Raised when a kit's provenance manifest does not match on-disk files."""


DEFAULT_IGNORE_NAMES = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "node_modules",
}


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _root_hash(files: Dict[str, str]) -> str:
    """Deterministic root hash over a sorted map of relative paths to digests."""
    canonical = "".join(f"{rel}:{digest}\n" for rel, digest in sorted(files.items()))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _collect_files(
    root: Path,
    output_name: str,
    ignore_names: Optional[Set[str]] = None,
) -> Dict[str, str]:
    ignore = set(ignore_names or DEFAULT_IGNORE_NAMES)
    ignore.add(output_name)
    files: Dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in ignore for part in path.parts):
            continue
        rel = path.relative_to(root).as_posix()
        files[rel] = _sha256_file(path)
    return files


def build_provenance(
    root_dir: str | Path,
    output_name: str = "provenance.json",
    ignore_names: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """Write a provenance manifest for ``root_dir`` and return it."""
    root = Path(root_dir).resolve()
    files = _collect_files(root, output_name, ignore_names)
    manifest: Dict[str, Any] = {
        "schema": "universal_kernel.provenance.v1",
        "algorithm": "sha256",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "root_hash": _root_hash(files),
        "files": files,
    }
    out_path = root / output_name
    out_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def verify_kit(manifest_path: str | Path) -> bool:
    """Verify every file digest and the manifest root-hash signature."""
    manifest_path = Path(manifest_path).resolve()
    if not manifest_path.is_file():
        raise ProvenanceMismatch(f"manifest not found: {manifest_path}")
    root = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    files: Dict[str, str] = dict(manifest.get("files") or {})
    expected_root = manifest.get("root_hash")
    if not expected_root:
        raise ProvenanceMismatch("manifest missing root_hash signature")

    for rel_path, expected_digest in files.items():
        file_path = root / rel_path
        if not file_path.is_file():
            raise ProvenanceMismatch(f"missing file: {rel_path}")
        actual_digest = _sha256_file(file_path)
        if actual_digest != expected_digest:
            raise ProvenanceMismatch(
                f"digest mismatch for {rel_path}: expected {expected_digest}, got {actual_digest}"
            )

    actual_root = _root_hash(files)
    if actual_root != expected_root:
        raise ProvenanceMismatch(
            f"root hash mismatch: expected {expected_root}, got {actual_root}"
        )

    return True


def sha256_of_file(path: str | Path) -> str:
    """Convenience helper for computing the sha256 digest of a single file."""
    return _sha256_file(Path(path))
