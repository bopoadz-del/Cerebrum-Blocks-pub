"""Registry integrity: every registered block name resolves to a loadable class."""

import pytest

from app.blocks import BLOCK_REGISTRY


@pytest.mark.asyncio
async def test_all_registry_blocks_load():
    """Every block the registry advertises must import without crashing."""
    failures = []
    loaded = []
    for name in BLOCK_REGISTRY.keys():
        try:
            cls = BLOCK_REGISTRY[name]
            loaded.append((name, cls.__name__))
        except Exception as exc:  # noqa: BLE001
            failures.append((name, str(exc)))

    assert len(loaded) == len(BLOCK_REGISTRY), (
        f"Only {len(loaded)}/{len(BLOCK_REGISTRY)} blocks loaded; failures: {failures}"
    )
    assert not failures, f"Block import failures: {failures}"


@pytest.mark.asyncio
async def test_no_dangling_block_references():
    """Ensure every module/class path in the registry exists at import time."""
    from app.blocks import _BLOCK_DEFS

    dangling = []
    for name, (module_path, class_name) in _BLOCK_DEFS.items():
        try:
            module = __import__(module_path, fromlist=[class_name])
            if not hasattr(module, class_name):
                dangling.append((name, module_path, class_name))
        except Exception as exc:  # noqa: BLE001
            dangling.append((name, module_path, f"{class_name}: {exc}"))

    assert not dangling, f"Dangling block references: {dangling}"
