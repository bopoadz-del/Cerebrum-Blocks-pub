"""Load domain kits from env + installed registry into BLOCK_REGISTRY specs."""

from __future__ import annotations

import ast
import importlib
import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.core.domain_kit_registry import enabled_kit_ids, load_registry

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
_KITS_DIR = _ROOT / "block_store" / "kits"
_BLOCKS_DIR = _ROOT / "app" / "blocks"


def _module_source(module: str) -> Optional[Path]:
    base = _ROOT.joinpath(*module.split("."))
    for path in (base.with_suffix(".py"), base / "__init__.py"):
        if path.is_file():
            return path
    return None


def _declaring_class(block_id: str) -> Optional[str]:
    """The class in app/blocks/<id> that declares ``name = "<id>"``.

    Read from the source (no import): a block says its own id, so its spec is
    derived, never kept in a table.
    """
    for path in (_BLOCKS_DIR / f"{block_id}.py", _BLOCKS_DIR / block_id / "__init__.py"):
        if not path.is_file():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            logger.warning("block %s source does not parse (%s); not registered", block_id, exc)
            return None
        found = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for stmt in node.body:
                target = stmt.targets[0] if isinstance(stmt, ast.Assign) else getattr(stmt, "target", None)
                value = getattr(stmt, "value", None)
                if (isinstance(target, ast.Name) and target.id == "name"
                        and isinstance(value, ast.Constant) and value.value == block_id):
                    found.append(node.name)
        return found[0] if len(found) == 1 else None
    return None


def _derive_kit_specs() -> Dict[str, List[Tuple[str, str, str]]]:
    """kit id -> [(name, module, class)], from each kit's own manifest.

    The container is the manifest's ``container.class``; each declared block
    the registry does not already define is ``app.blocks.<id>`` and the class
    that declares that id. A block whose source does not exist is not listed
    -- a kit never advertises a block nobody wrote.
    """
    from app.blocks import _EXTENDED_BLOCK_DEFS, _GENERIC_BLOCK_DEFS

    # Generic blocks are always registered; everything else registers on a
    # virgin boot only when a kit that declares it is enabled.
    always = set(_GENERIC_BLOCK_DEFS)
    out: Dict[str, List[Tuple[str, str, str]]] = {}
    for manifest_path in sorted(_KITS_DIR.glob("*/manifest.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        kit_id = str(manifest.get("id") or manifest_path.parent.name)
        specs: List[Tuple[str, str, str]] = []
        container = (manifest.get("container") or {}).get("class") or ""
        if "." in container:
            module, cls = container.rsplit(".", 1)
            if _module_source(module) is not None:
                specs.append((kit_id, module, cls))
        blocks = manifest.get("blocks")
        for block_id in blocks if isinstance(blocks, list) else []:
            if block_id in always:
                continue
            if block_id in _EXTENDED_BLOCK_DEFS:
                module, cls = _EXTENDED_BLOCK_DEFS[block_id]
                specs.append((block_id, module, cls))
                continue
            cls = _declaring_class(block_id)
            if cls is None:
                logger.debug("kit %s declares block %s with no source that names it", kit_id, block_id)
                continue
            specs.append((block_id, f"app.blocks.{block_id}", cls))
        if specs:
            out[kit_id] = specs
    return out


_KIT_BLOCK_SPECS_CACHE: Optional[Dict[str, List[Tuple[str, str, str]]]] = None


def kit_spec_map() -> Dict[str, List[Tuple[str, str, str]]]:
    global _KIT_BLOCK_SPECS_CACHE
    if _KIT_BLOCK_SPECS_CACHE is None:
        _KIT_BLOCK_SPECS_CACHE = _derive_kit_specs()
    return _KIT_BLOCK_SPECS_CACHE


def __getattr__(name: str):
    # Back-compat: _KIT_BLOCK_SPECS is now derived from the kit manifests.
    if name == "_KIT_BLOCK_SPECS":
        return kit_spec_map()
    raise AttributeError(name)


def _env_kit_ids() -> list[str]:
    raw = os.getenv("CEREBRUM_DOMAIN_KITS", "").strip()
    if not raw:
        return []
    return [k.strip() for k in raw.split(",") if k.strip()]


def active_kit_ids() -> list[str]:
    ids = set(_env_kit_ids())
    ids.update(enabled_kit_ids())
    return sorted(ids)


def is_virgin_boot() -> bool:
    if os.getenv("CEREBRUM_VIRGIN", "true").strip().lower() in ("0", "false", "no"):
        return False
    return len(active_kit_ids()) == 0


def kit_block_specs() -> List[Tuple[str, str, str]]:
    specs: List[Tuple[str, str, str]] = []
    for kit_id in active_kit_ids():
        kit_specs = kit_spec_map().get(kit_id)
        if not kit_specs:
            logger.warning("domain kit '%s' has no block spec map — skipped", kit_id)
            continue
        specs.extend(kit_specs)
    return specs


def verify_installed_containers() -> None:
    for kit_id, record in load_registry().get("kits", {}).items():
        class_path = record.get("container_class", "")
        if not class_path or "." not in class_path:
            continue
        module_path, class_name = class_path.rsplit(".", 1)
        try:
            mod = importlib.import_module(module_path)
            getattr(mod, class_name)
        except Exception as exc:
            logger.warning(
                "installed kit '%s' container %s failed to import: %s",
                kit_id, class_path, exc,
            )
