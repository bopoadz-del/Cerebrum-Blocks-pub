"""Container kit discovery and install — Cerebrum Block Store layer.

Fork stays the live production runtime. This module publishes Fork-authored
kits for discovery and installs them into consumer Cerebrum instances.

Skeleton kits (``status`` draft / coming_soon) keep source stubs at the kit root
(``container.py``, ``knowledge.py``, ``prompts/``, …) and list them in manifest
``skeleton_artifacts`` for discovery. Install copies only from ``bundle/`` via
``artifacts``; skeleton kits are not installable until ``status`` is ``available``
(or legacy published kits with a complete ``bundle/``).
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
KITS_DIR = PROJECT_ROOT / "block_store" / "kits"
INSTALL_STATE_PATH = PROJECT_ROOT / "data" / "installed_container_kits.json"


class ContainerKitError(Exception):
    """Raised when kit lookup or install fails."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_install_state(state: dict[str, Any]) -> None:
    INSTALL_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(INSTALL_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def _load_install_state() -> dict[str, Any]:
    if not INSTALL_STATE_PATH.exists():
        return {"kits": {}}
    return _load_json(INSTALL_STATE_PATH)


def _kit_dir(kit_id: str) -> Path:
    return KITS_DIR / kit_id


def _manifest_path(kit_id: str) -> Path:
    return _kit_dir(kit_id) / "manifest.json"


def _load_manifest(manifest_path: Path) -> dict[str, Any]:
    manifest = _load_json(manifest_path)
    kit_dir = manifest_path.parent
    manifest.setdefault("id", kit_dir.name)
    bundle_ready = _bundle_ready(kit_dir, manifest)
    skeleton_ready = _skeleton_ready(kit_dir, manifest)
    manifest["bundle_ready"] = bundle_ready
    manifest["skeleton_ready"] = skeleton_ready
    manifest["installable"] = _installable(manifest, bundle_ready, skeleton_ready)
    manifest["skeleton_installable"] = _skeleton_installable(manifest, skeleton_ready)
    manifest["coming_soon"] = manifest.get("status") == "coming_soon"
    return manifest


def _bundle_ready(kit_dir: Path, manifest: dict[str, Any]) -> bool:
    bundle = kit_dir / "bundle"
    artifacts = manifest.get("artifacts") or []
    if not artifacts:
        return False
    return all((bundle / item["src"]).exists() for item in artifacts)


def _skeleton_ready(kit_dir: Path, manifest: dict[str, Any]) -> bool:
    """True when kit-root skeleton files exist (see ``skeleton_artifacts``)."""
    skeleton = manifest.get("skeleton_artifacts") or []
    if not skeleton:
        return (kit_dir / "container.py").is_file()
    return all((kit_dir / item["src"]).exists() for item in skeleton)


def _skeleton_installable(manifest: dict[str, Any], skeleton_ready: bool) -> bool:
    """Coming-soon / draft kits may install skeleton artifacts only."""
    if not skeleton_ready:
        return False
    skeleton = manifest.get("skeleton_artifacts") or []
    return bool(skeleton)


def _installable(
    manifest: dict[str, Any], bundle_ready: bool, skeleton_ready: bool = False
) -> bool:
    status = manifest.get("status")
    if status in ("draft", "coming_soon"):
        return _skeleton_installable(manifest, skeleton_ready)
    if status == "available":
        return bundle_ready
    # Legacy construction kit and future published kits without explicit status
    return bundle_ready


def list_kits() -> list[dict[str, Any]]:
    if not KITS_DIR.exists():
        return []
    kits: list[dict[str, Any]] = []
    for kit_dir in sorted(KITS_DIR.iterdir()):
        if not kit_dir.is_dir() or kit_dir.name.startswith("_"):
            continue
        manifest_path = kit_dir / "manifest.json"
        if manifest_path.exists():
            kits.append(_load_manifest(manifest_path))
    return kits


def get_kit(kit_id: str) -> dict[str, Any]:
    manifest_path = _manifest_path(kit_id)
    if not manifest_path.exists():
        raise ContainerKitError(f"Container kit '{kit_id}' not found")
    return _load_manifest(manifest_path)


def list_installed() -> dict[str, Any]:
    return _load_install_state()


def install_kit(
    kit_id: str,
    *,
    target_root: Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    manifest = get_kit(kit_id)
    if not manifest.get("installable"):
        status = manifest.get("status") or "unknown"
        raise ContainerKitError(
            f"Kit '{kit_id}' is not installable (status={status!r}). "
            "Skeleton kits require skeleton_artifacts; full kits need bundle/ + status=available."
        )

    target = (target_root or PROJECT_ROOT).resolve()
    bundle_dir = _kit_dir(kit_id) / "bundle"
    kit_dir = _kit_dir(kit_id)
    artifacts = manifest.get("artifacts") or []
    skeleton_mode = not manifest.get("bundle_ready") and manifest.get("skeleton_installable")

    provenance_status = _verify_kit_provenance(kit_id, kit_dir)

    if skeleton_mode:
        result = _install_skeleton_kit(kit_id, manifest, kit_dir, target, force=force)
        result["provenance"] = provenance_status
        return result

    if not artifacts:
        raise ContainerKitError(f"Kit '{kit_id}' has no install artifacts")

    missing = [
        item["src"]
        for item in artifacts
        if not (bundle_dir / item["src"]).exists()
    ]
    if missing:
        raise ContainerKitError(
            f"Kit '{kit_id}' bundle incomplete — run scripts/publish_construction_kit.py. "
            f"Missing: {', '.join(missing[:5])}"
            + (f" (+{len(missing) - 5} more)" if len(missing) > 5 else "")
        )

    copied: list[str] = []
    skipped: list[dict[str, str]] = []

    for item in artifacts:
        src = bundle_dir / item["src"]
        dest = target / item["dest"]
        if dest.exists() and not force:
            skipped.append({"dest": item["dest"], "reason": "already_exists"})
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied.append(item["dest"])

    state = _load_install_state()
    state.setdefault("kits", {})
    state["kits"][kit_id] = {
        "version": manifest.get("version"),
        "installed_at": _utc_now(),
        "target_root": str(target),
        "files": copied,
    }
    _save_install_state(state)

    registry_entry = _register_kit_on_target(kit_id, manifest, target)

    return {
        "status": "success",
        "kit_id": kit_id,
        "version": manifest.get("version"),
        "target_root": str(target),
        "copied": copied,
        "skipped": skipped,
        "installed_at": state["kits"][kit_id]["installed_at"],
        "registry": registry_entry,
        "install_mode": "bundle",
        "provenance": provenance_status,
    }


def _verify_kit_provenance(kit_id: str, kit_dir: Path) -> str:
    """Verify the kit's provenance manifest on the install path.

    A kit that ships ``provenance.json`` must verify — digest or root-hash
    mismatches refuse the install (fail closed). A kit without one installs
    but the result says so explicitly; nothing is silently assumed verified.
    """
    from block_store.kits.universal_kernel.wave1.provenance_verification import (
        ProvenanceMismatch,
        verify_kit,
    )

    provenance_path = kit_dir / "provenance.json"
    if not provenance_path.is_file():
        return "absent — unverified"
    try:
        verify_kit(provenance_path)
    except ProvenanceMismatch as exc:
        raise ContainerKitError(
            f"Kit '{kit_id}' failed provenance verification: {exc}"
        ) from exc
    return "verified"


def _install_skeleton_kit(
    kit_id: str,
    manifest: dict[str, Any],
    kit_dir: Path,
    target: Path,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Copy skeleton_artifacts from kit root (coming-soon / draft kits)."""
    artifacts = manifest.get("skeleton_artifacts") or []
    if not artifacts:
        raise ContainerKitError(f"Kit '{kit_id}' has no skeleton artifacts")

    missing = [item["src"] for item in artifacts if not (kit_dir / item["src"]).exists()]
    if missing:
        raise ContainerKitError(
            f"Kit '{kit_id}' skeleton incomplete. Missing: {', '.join(missing[:5])}"
            + (f" (+{len(missing) - 5} more)" if len(missing) > 5 else "")
        )

    copied: list[str] = []
    skipped: list[dict[str, str]] = []
    for item in artifacts:
        src = kit_dir / item["src"]
        dest = target / item["dest"]
        if dest.exists() and not force:
            skipped.append({"dest": item["dest"], "reason": "already_exists"})
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied.append(item["dest"])

    state = _load_install_state()
    state.setdefault("kits", {})
    state["kits"][kit_id] = {
        "version": manifest.get("version"),
        "installed_at": _utc_now(),
        "target_root": str(target),
        "files": copied,
        "install_mode": "skeleton",
    }
    _save_install_state(state)
    registry_entry = _register_kit_on_target(kit_id, manifest, target)

    return {
        "status": "success",
        "kit_id": kit_id,
        "version": manifest.get("version"),
        "target_root": str(target),
        "copied": copied,
        "skipped": skipped,
        "installed_at": state["kits"][kit_id]["installed_at"],
        "registry": registry_entry,
        "install_mode": "skeleton",
    }


def _register_kit_on_target(
    kit_id: str, manifest: dict[str, Any], target: Path
) -> dict[str, Any]:
    """Write domain_kit_registry.json on the install target for boot-time registration."""
    container = manifest.get("container") or {}
    container_class = container.get("class", "")
    blocks = manifest.get("blocks") or []
    version = manifest.get("version")

    registry_path = target / "data" / "domain_kit_registry.json"
    if registry_path.exists():
        with open(registry_path, encoding="utf-8") as f:
            registry = json.load(f)
    else:
        registry = {"kits": {}}
    registry.setdefault("kits", {})
    registry["kits"][kit_id] = {
        "container_class": container_class,
        "blocks": blocks,
        "version": version,
    }
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    with open(registry_path, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2)

    return registry["kits"][kit_id]


def _unregister_kit_on_target(kit_id: str, target: Path) -> None:
    registry_path = target / "data" / "domain_kit_registry.json"
    if not registry_path.exists():
        return
    with open(registry_path, encoding="utf-8") as f:
        registry = json.load(f)
    registry.get("kits", {}).pop(kit_id, None)
    with open(registry_path, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2)


def uninstall_kit(kit_id: str, *, target_root: Path | None = None) -> dict[str, Any]:
    """Remove installed files listed in the last install record."""
    state = _load_install_state()
    record = state.get("kits", {}).get(kit_id)
    if not record:
        raise ContainerKitError(f"Kit '{kit_id}' is not installed")

    target = Path(record.get("target_root") or target_root or PROJECT_ROOT).resolve()
    removed: list[str] = []
    for rel_path in record.get("files", []):
        path = target / rel_path
        if path.exists():
            path.unlink()
            removed.append(rel_path)

    _unregister_kit_on_target(kit_id, target)

    del state["kits"][kit_id]
    _save_install_state(state)
    return {"status": "success", "kit_id": kit_id, "removed": removed}
