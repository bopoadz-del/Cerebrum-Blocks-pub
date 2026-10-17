#!/usr/bin/env python3
"""
Test script for block_registry blocks.
Validates block.json schema and tests inline execution.

Run from repository root:
    python scripts/test_block_registry.py [block_name ...]
"""

import json

import pytest

pytestmark = pytest.mark.manual_script
import subprocess
import sys
from pathlib import Path

REGISTRY_ROOT = Path("block_registry")
TEST_INPUTS = {
    "chat": {"input": "Hello, what can you do?"},
    "pdf": {"input": {"file_path": "test.pdf"}},
    "ocr": {"input": {"file_path": "test.png"}},
    "web": {"input": "https://example.com"},
    "search": {"input": "construction AI"},
    "image": {"input": "a robot building a house"},
    "code": {"input": "print('hello world')"},
    "auth": {"input": {"action": "create_key", "owner": "test"}},
    "translate": {"input": "Hello world"},
    "voice": {"input": "Hello, this is a test"},
}


def validate_manifest(path: Path) -> list:
    """Validate block.json structure. Returns list of errors."""
    errors = []
    with open(path) as f:
        manifest = json.load(f)

    required = [
        "id",
        "name",
        "version",
        "description",
        "inputs",
        "outputs",
        "execution",
        "ui_schema",
        "trust_tier",
    ]
    for key in required:
        if key not in manifest:
            errors.append(f"Missing required field: {key}")

    if "execution" in manifest:
        exec_cfg = manifest["execution"]
        if "type" not in exec_cfg:
            errors.append("Missing execution.type")
        if "image" not in exec_cfg:
            errors.append("Missing execution.image")

    return errors


def test_inline_execution(block_name: str) -> dict:
    """Run the block via its run.py wrapper with test input."""
    block_dir = REGISTRY_ROOT / block_name
    run_script = block_dir / "block.py"

    if not run_script.exists():
        return {"success": False, "error": f"Missing {run_script}"}

    test_input = TEST_INPUTS.get(block_name, {"input": "test"})

    # We test the adapter directly (not the universal run.py) since we don't have the full app installed
    # The adapter imports app.blocks which requires the backend environment
    # For a quick smoke test, we just validate the syntax
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(run_script)],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return {"success": False, "error": f"Syntax error: {result.stderr}"}

    return {"success": True, "note": "Syntax OK (full execution requires backend environment)"}


def main():
    if len(sys.argv) > 1:
        blocks = sys.argv[1:]
    else:
        blocks = [d.name for d in REGISTRY_ROOT.iterdir() if d.is_dir()]

    print("=" * 60)
    print("Block Registry Test Suite")
    print("=" * 60)

    passed = 0
    failed = 0

    for name in sorted(blocks):
        block_dir = REGISTRY_ROOT / name
        manifest_path = block_dir / "block.json"

        print(f"\n--> {name}")

        if not manifest_path.exists():
            print(f"  [FAIL] Missing block.json")
            failed += 1
            continue

        # Validate manifest
        errors = validate_manifest(manifest_path)
        if errors:
            for err in errors:
                print(f"  [FAIL] {err}")
            failed += 1
            continue
        print(f"  [OK] block.json valid")

        # Test execution adapter
        result = test_inline_execution(name)
        if result["success"]:
            print(f"  [OK] {result.get('note', 'Execution OK')}")
            passed += 1
        else:
            print(f"  [FAIL] {result['error']}")
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"Results: {passed} passed, {failed} failed")
    print(f"{'=' * 60}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
