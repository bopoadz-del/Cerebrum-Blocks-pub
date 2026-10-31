"""Execution harness the sandbox runner invokes for a registry block adapter.

The runner runs each block out-of-process as its own subprocess. The adapters
expose a ``run(**payload)`` function but no ``__main__`` of their own, so this
harness is the entrypoint the runner executes:

    python run_adapter.py <adapter_path>   # payload as JSON on stdin

It loads the adapter module, calls ``run(**payload)``, and writes the runner's
contract to stdout: ``{"success": true, "output": <result>}``. An adapter that
raises (several adapters raise to signal a block-level error such as an honest
``not_implemented`` refusal) is reported as an error *result* -- the block ran
and produced an error, which the caller reads -- not as a transport failure, so
the envelope stays ``success: true`` with the error inside ``output``.
"""

from __future__ import annotations

import importlib.util
import json
import sys


def _load_run(adapter_path: str):
    spec = importlib.util.spec_from_file_location("block_adapter", adapter_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load adapter: {adapter_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    run = getattr(module, "run", None)
    if not callable(run):
        raise AttributeError(f"adapter has no run(): {adapter_path}")
    return run


def main() -> None:
    adapter_path = sys.argv[1]
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {"input": payload}
    try:
        result = _load_run(adapter_path)(**payload)
        envelope = {"success": True, "output": result}
    except Exception as exc:  # noqa: BLE001 — an adapter error is a result, not a crash
        envelope = {"success": True, "output": {"status": "error", "error": str(exc)}}
    sys.stdout.write(json.dumps(envelope, default=str))


if __name__ == "__main__":
    main()
