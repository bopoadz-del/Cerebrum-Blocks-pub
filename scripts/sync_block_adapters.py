#!/usr/bin/env python3
"""Upgrade registry adapters to call UniversalBlock.execute() instead of process()."""

from pathlib import Path

ROOT = Path(__file__).parent.parent
REGISTRY = ROOT / "block_registry"
SKIP = {"__pycache__"}

OLD_SNIPPET = "instance.process(input_data, params)"
NEW_ADAPTER = '''def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as pool:
        return pool.submit(asyncio.run, coro).result()


def run(**kwargs):
    block_cls = BLOCK_REGISTRY["{name}"]
    instance = block_cls()

    input_data = kwargs.get("input", kwargs)
    params = {{k: v for k, v in kwargs.items() if k != "input"}}

    envelope = _run_async(instance.execute(input_data, params))
    if envelope.get("status") == "error":
        inner = envelope.get("result", {{}})
        message = inner.get("error") if isinstance(inner, dict) else str(inner)
        raise RuntimeError(message or "{name} block failed")

    return envelope.get("result", envelope)
'''


def upgrade_adapter(path: Path, block_name: str) -> bool:
    text = path.read_text(encoding="utf-8", errors="replace")
    if "def run(" not in text or "BLOCK_REGISTRY" not in text:
        return False
    if "instance.execute(" in text:
        return False

    header = text.split("def run", 1)[0]
    header = header.replace(".process()", ".execute()")
    new_text = header + NEW_ADAPTER.format(name=block_name)
    path.write_text(new_text, encoding="utf-8")
    return True


def main() -> int:
    updated = 0
    for block_dir in sorted(REGISTRY.iterdir()):
        if not block_dir.is_dir() or block_dir.name in SKIP:
            continue
        adapter = block_dir / "block.py"
        if adapter.exists() and upgrade_adapter(adapter, block_dir.name):
            updated += 1
            print(f"[OK] upgraded {block_dir.name}/block.py")
    print(f"Updated {updated} adapters")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
