#!/usr/bin/env python3
"""Universal wrapper for Cerebrum blocks.

Reads JSON from stdin, executes block.run(inputs), writes JSON to stdout.
When run inside the per-block container, this wrapper also reads the block
manifest so it can self-confine when the operator forgot to set the container
runtime flags (e.g. ``--network=none``).
"""

import json
import os
import sys
import traceback
from pathlib import Path


def _load_capabilities():
    """Read permissions from the adjacent ``block.json`` if present."""
    manifest_path = Path(__file__).with_name("block.json")
    if not manifest_path.exists():
        return {}
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8")).get("permissions", {}) or {}
    except (json.JSONDecodeError, OSError):
        return {}


def _enforce_self_confinement(permissions: dict) -> None:
    """Best-effort runtime guard against misconfigured containers.

    This is a safety net, not the primary isolation boundary. The real
    sandboxing is provided by the container runtime (``--network=none``,
    ``--read-only``, ``--cap-drop=ALL``) or the sandbox-runner service.
    """
    network_allowed = bool(permissions.get("network", False))
    if not network_allowed and os.getenv("SANDBOX_NETWORK") != "none":
        # Print to stderr so it shows up in logs but not the JSON result.
        print(
            "WARNING: block declares network=false but SANDBOX_NETWORK is not 'none'",
            file=sys.stderr,
        )


def main():
    # Read input JSON from stdin
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(json.dumps({"success": False, "error": f"Invalid JSON input: {e}"}))
        sys.exit(1)

    # Import the block's run function
    try:
        from block import run
    except ImportError as e:
        print(json.dumps({"success": False, "error": f"block.py must define a 'run' function: {e}"}))
        sys.exit(1)

    permissions = _load_capabilities()
    _enforce_self_confinement(permissions)

    # Execute the block
    try:
        result = run(**input_data)
        output = {"success": True, "output": result}
    except Exception as e:
        output = {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }
        print(json.dumps(output))
        sys.exit(1)

    print(json.dumps(output))
    sys.stdout.flush()
    sys.exit(0)


if __name__ == "__main__":
    main()
