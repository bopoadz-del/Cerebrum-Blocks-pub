#!/usr/bin/env python3
"""B04 — every advertised store block must actually be there.

The shelf is ``block_registry/<id>/block.json``. Advertising a name that
does not import, has no declared entrypoint, or carries no identity
metadata is a lie. This census walks the advertised names in sorted
order and stops on the first failure so the store is fixed one honest
block at a time.

Usage:
  python scripts/census_registry.py
  python scripts/census_registry.py --json
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
REGISTRY_ROOT = REPO_ROOT / "block_registry"

# Identity the Store must be able to state for every advertised block.
# execution / ui_schema are a later standards gate, not this honesty gate.
# description may be empty on a signed manifest (rewriting it breaks the
# digest); the class/docstring is then the carrier.
IDENTITY_KEYS = ("id", "name", "version")

# Blocks whose implementation is not ``app.blocks.<id>`` / the kit maps.
# Keep this map short and named: a new special case is a census finding
# until it is either conventional or listed here with a reason.
SPECIAL_ENTRYPOINTS: dict[str, tuple[str, str]] = {
    "action_contract": ("app.blocks.core.action_contract", "execute_action"),
    "construction": ("app.containers.construction", "ConstructionContainer"),
    "insurance": ("app.containers.insurance", "InsuranceContainer"),
    "finance_ops": ("app.containers.finance_ops", "FinanceOpsContainer"),
    "document_engine": ("app.blocks.document_engine", "DocumentEngineBlock"),
}


@dataclass(frozen=True)
class Finding:
    block: str
    reason: str

    def __str__(self) -> str:
        return f"{self.block}: {self.reason}"


def advertised_blocks(root: Path | None = None) -> list[Path]:
    registry = Path(root) if root is not None else REGISTRY_ROOT
    return sorted(
        p
        for p in registry.iterdir()
        if p.is_dir() and p.name != "__pycache__" and (p / "block.json").is_file()
    )


def load_manifest(block_dir: Path) -> dict[str, Any]:
    return json.loads((block_dir / "block.json").read_text(encoding="utf-8"))


def known_entrypoints() -> dict[str, tuple[str, str]]:
    """Name → (module, entrypoint) from the runtime maps plus specials."""
    from app.blocks import _EXTENDED_BLOCK_DEFS, _GENERIC_BLOCK_DEFS
    from app.core.domain_kit_loader import _KIT_BLOCK_SPECS

    out: dict[str, tuple[str, str]] = {}
    out.update(_GENERIC_BLOCK_DEFS)
    out.update(_EXTENDED_BLOCK_DEFS)
    for specs in _KIT_BLOCK_SPECS.values():
        for name, module, class_name in specs:
            out[name] = (module, class_name)
    out.update(SPECIAL_ENTRYPOINTS)
    return out


def _camel_entry(name: str) -> str:
    parts = name.split("_")
    if parts and parts[-1] == "v2":
        return "".join(p.title() for p in parts[:-1]) + "BlockV2"
    return "".join(p.title() for p in parts) + "Block"


def resolve_entrypoint(name: str) -> tuple[str, str]:
    known = known_entrypoints()
    if name in known:
        return known[name]
    return f"app.blocks.{name}", _camel_entry(name)


def missing_identity(manifest: dict[str, Any]) -> list[str]:
    missing = []
    for key in IDENTITY_KEYS:
        value = manifest.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(key)
    return missing


def _carries_description(target: Any, manifest: dict[str, Any]) -> bool:
    """Manifest, class attribute, or docstring — one honest sentence is enough."""
    declared = manifest.get("description")
    if isinstance(declared, str) and declared.strip():
        return True
    attr = getattr(target, "description", None)
    if isinstance(attr, str) and attr.strip():
        return True
    doc = getattr(target, "__doc__", None)
    return isinstance(doc, str) and bool(doc.strip())


def inspect_block(block_dir: Path) -> Finding | None:
    """Return the first honesty failure for this advertised block, or None."""
    name = block_dir.name
    try:
        manifest = load_manifest(block_dir)
    except (OSError, json.JSONDecodeError) as exc:
        return Finding(name, f"block.json unreadable: {exc}")

    missing = missing_identity(manifest)
    if missing:
        return Finding(name, f"manifest missing metadata: {', '.join(missing)}")
    if str(manifest.get("id") or "") != name:
        return Finding(
            name,
            f"manifest id {manifest.get('id')!r} does not match folder {name!r}",
        )

    module_path, entry = resolve_entrypoint(name)
    try:
        module = importlib.import_module(module_path)
    except Exception as exc:  # noqa: BLE001 — census must name the import
        return Finding(name, f"module {module_path} failed to import: {exc}")

    if not hasattr(module, entry):
        return Finding(name, f"module {module_path} has no entrypoint {entry}")

    target = getattr(module, entry)
    if not callable(target):
        return Finding(name, f"entrypoint {module_path}.{entry} is not callable")

    if not _carries_description(target, manifest):
        return Finding(
            name,
            f"{module_path}.{entry} carries no description "
            "(manifest, class attribute, or docstring)",
        )

    # Class-shaped blocks carry identity on the class. Function entrypoints
    # (action_contract.execute_action) carry it on the signed manifest only.
    class_name = getattr(target, "name", None)
    if isinstance(class_name, str) and class_name and class_name != name:
        return Finding(
            name,
            f"class name {class_name!r} does not match advertised id {name!r}",
        )
    return None


def first_missing(root: Path | None = None) -> Finding | None:
    """The gate: stop on the first advertised block that is not honest."""
    registry = Path(root) if root is not None else REGISTRY_ROOT
    for block_dir in advertised_blocks(registry):
        finding = inspect_block(block_dir)
        if finding is not None:
            return finding
    return None


def all_findings(root: Path | None = None) -> list[Finding]:
    registry = Path(root) if root is not None else REGISTRY_ROOT
    return [
        finding
        for block_dir in advertised_blocks(registry)
        if (finding := inspect_block(block_dir)) is not None
    ]


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the first finding as JSON (or {\"missing\": 0}).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="List every finding. The gate itself still fails on the first.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=REGISTRY_ROOT,
        help="Registry directory (default: root block_registry/).",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    advertised = advertised_blocks(args.root)
    if not advertised:
        print("census: no advertised blocks — the shelf is empty", file=sys.stderr)
        return 1

    if args.all:
        findings = all_findings(args.root)
        if args.json:
            print(json.dumps([asdict(f) for f in findings], indent=2))
        elif findings:
            print("REGISTRY CENSUS — advertised blocks that do not resolve:")
            for finding in findings:
                print(f"  {finding}")
            print(f"TOTAL: {len(findings)}")
        else:
            print(f"census: 0 missing ({len(advertised)} advertised)")
        first = findings[0] if findings else None
    else:
        first = first_missing(args.root)
        if args.json:
            payload = {"missing": 0} if first is None else asdict(first)
            print(json.dumps(payload, indent=2))
        elif first is None:
            print(f"census: 0 missing ({len(advertised)} advertised)")
        else:
            print(f"REGISTRY CENSUS — first missing block:\n  {first}")

    return 1 if first is not None else 0


if __name__ == "__main__":
    sys.exit(main())
