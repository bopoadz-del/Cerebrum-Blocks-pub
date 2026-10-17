"""Block-contract tests generated from declared input/output schemas."""

import pytest

from app.blocks import BLOCK_REGISTRY
from app.core.typed_block import TypedBlock


@pytest.mark.asyncio
async def test_typed_blocks_have_schemas():
    """Every TypedBlock subclass must declare non-empty input/output schemas."""
    failures = []
    for name in BLOCK_REGISTRY.keys():
        try:
            cls = BLOCK_REGISTRY[name]
        except Exception as exc:  # noqa: BLE001
            failures.append((name, f"import failed: {exc}"))
            continue
        if not issubclass(cls, TypedBlock):
            continue
        if cls.input_schema is None:
            failures.append((name, "missing input_schema"))
        if cls.output_schema is None:
            failures.append((name, "missing output_schema"))

    assert not failures, f"Schema contract failures: {failures}"


@pytest.mark.asyncio
async def test_aviation_blocks_declared():
    """The eight aviation POC blocks must be present in the registry."""
    expected = {
        "aviation_v2",
        "aviation_grounding_gate",
        "aviation_chat_server",
        "aviation_pss_kit",
        "aviation_revenue_kit",
        "aviation_loyalty_kit",
        "aviation_cargo_kit",
        "aviation_cx_kit",
    }
    missing = expected - set(BLOCK_REGISTRY.keys())
    assert not missing, f"Missing aviation blocks: {missing}"
