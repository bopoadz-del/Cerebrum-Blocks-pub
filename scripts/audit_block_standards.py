#!/usr/bin/env python3
"""Audit block_registry entries against the Cerebrum plug-and-play standard."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Load the pin without importing app.core (that package pulls the API stack).
_spec = importlib.util.spec_from_file_location(
    "trust_tier_pin", ROOT / "app" / "core" / "trust_tier.py"
)
_trust = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_trust)
check_trust_tier = _trust.check_trust_tier

# Same treatment for the contract fields (KERNEL_DEFAULTS 1.2 / L2.2).
# manifest_contract.py resolves the BlockResult status set by path when it is
# loaded this way, so there is still only one definition of the four.
_spec_contract = importlib.util.spec_from_file_location(
    "manifest_contract_pin", ROOT / "app" / "core" / "manifest_contract.py"
)
_contract = importlib.util.module_from_spec(_spec_contract)
assert _spec_contract.loader is not None
_spec_contract.loader.exec_module(_contract)
check_contract_fields = _contract.check_contract_fields
CONTRACT_MANIFEST_KEYS = _contract.CONTRACT_MANIFEST_KEYS
check_brief_scope_fields = _contract.check_brief_scope_fields
missing_brief_scope_fields = _contract.missing_brief_scope_fields
BRIEF_SCOPE_FAIL_CLOSED = _contract.BRIEF_SCOPE_FAIL_CLOSED
BRIEF_SCOPE_KEYS = _contract.BRIEF_SCOPE_KEYS

REGISTRY_ROOT = ROOT / "block_registry"
SKIP_DIRS = {"__pycache__"}

REQUIRED_MANIFEST_KEYS = [
    "id",
    "name",
    "version",
    "description",
    "inputs",
    "outputs",
    "execution",
    "ui_schema",
    "tags",
    "layer",
    "requires",
    "trust_tier",
]

RECOMMENDED_MANIFEST_KEYS = ["author"]


def audit_block(block_dir: Path) -> dict:
    name = block_dir.name
    result = {"block": name, "errors": [], "warnings": []}

    manifest_path = block_dir / "block.json"
    adapter_path = block_dir / "block.py"
    dockerfile_path = block_dir / "Dockerfile"

    if not manifest_path.exists():
        result["errors"].append("missing block.json")
        return result

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        result["errors"].append(f"invalid block.json: {exc}")
        return result

    for key in REQUIRED_MANIFEST_KEYS:
        if key not in manifest:
            result["errors"].append(f"missing required field: {key}")

    # Value-check trust_tier even when the key is present: an empty or
    # unknown tier is not a synonym for "fine". Distinct from publisher_tier.
    if "trust_tier" in manifest:
        for reason in check_trust_tier(manifest):
            if reason.startswith("missing required"):
                result["errors"].append("missing required field: trust_tier")
            else:
                result["errors"].append(reason)

    # Contract fields are OPTIONAL in this phase, so absence is silent. A
    # field that IS declared gets checked: a half-filled requires_inputs is
    # worse than none, because a planner reading it will guess or crash.
    for reason in check_contract_fields(manifest):
        result["errors"].append(reason)

    # L2.2 brief-scope fields: report-only until BRIEF_SCOPE_FAIL_CLOSED
    # flips. Missing or invalid reads/writes/never/acceptance are
    # warnings (or errors after the owner-gated flip). Empty lists pass.
    brief_invalid = check_brief_scope_fields(manifest)
    brief_missing = missing_brief_scope_fields(manifest)
    brief_notes = brief_invalid + [
        "missing brief-scope field: %s" % field for field in brief_missing
    ]
    if BRIEF_SCOPE_FAIL_CLOSED:
        result["errors"].extend(brief_notes)
    else:
        result["warnings"].extend(brief_notes)

    for key in RECOMMENDED_MANIFEST_KEYS:
        if not manifest.get(key):
            result["warnings"].append(f"missing recommended field: {key}")

    if manifest.get("id") != name:
        result["warnings"].append(f"id '{manifest.get('id')}' != folder '{name}'")

    execution = manifest.get("execution", {})
    exec_type = execution.get("type")
    if exec_type == "docker" and not execution.get("image"):
        result["errors"].append("execution.type=docker but execution.image missing")
    elif exec_type not in {"docker", "python"}:
        result["warnings"].append(f"unusual execution.type={exec_type!r}")

    ui_schema = manifest.get("ui_schema")
    if isinstance(ui_schema, dict):
        result["errors"].append("ui_schema must be an array of widgets, not an object")
    elif isinstance(ui_schema, list):
        input_names = {item.get("name") for item in manifest.get("inputs", []) if isinstance(item, dict)}
        widget_names = {item.get("name") for item in ui_schema if isinstance(item, dict)}
        missing = sorted(n for n in input_names - widget_names if n)
        if missing:
            result["warnings"].append(f"inputs missing ui widgets: {missing}")

    outputs = manifest.get("outputs", [])
    if not outputs:
        result["errors"].append("outputs must contain at least one item")

    if not adapter_path.exists():
        result["errors"].append("missing block.py")
    else:
        source = adapter_path.read_text(encoding="utf-8", errors="replace")
        if "def run" not in source:
            result["errors"].append("block.py must define run()")
        if "BLOCK_REGISTRY" in source and "instance.process(" in source:
            result["warnings"].append("adapter uses process() instead of execute() envelope")

    if not dockerfile_path.exists():
        result["errors"].append("missing Dockerfile")
    else:
        dockerfile = dockerfile_path.read_text(encoding="utf-8")
        if 'ENTRYPOINT ["python", "run.py"]' in dockerfile and "COPY" not in dockerfile:
            result["warnings"].append("Dockerfile uses run.py but does not COPY it (relies on base image)")

    return result


def main() -> int:
    if not REGISTRY_ROOT.exists():
        print(f"Registry not found: {REGISTRY_ROOT}")
        return 1

    blocks = sorted(
        p for p in REGISTRY_ROOT.iterdir() if p.is_dir() and p.name not in SKIP_DIRS
    )
    results = [audit_block(block_dir) for block_dir in blocks]

    errors = [r for r in results if r["errors"]]
    warnings = [r for r in results if r["warnings"]]

    print("=" * 72)
    print("Cerebrum Block Standards Audit")
    print("=" * 72)
    print(f"Blocks scanned: {len(results)}")
    print(f"Blocks with errors: {len(errors)}")
    print(f"Blocks with warnings: {len(warnings)}")
    print()

    if errors:
        print("ERRORS")
        print("-" * 72)
        for row in errors:
            print(f"{row['block']}")
            for item in row["errors"]:
                print(f"  - {item}")
        print()

    if warnings:
        print("WARNINGS")
        print("-" * 72)
        for row in warnings[:30]:
            print(f"{row['block']}: {'; '.join(row['warnings'])}")
        if len(warnings) > 30:
            print(f"... and {len(warnings) - 30} more")
        print()

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
