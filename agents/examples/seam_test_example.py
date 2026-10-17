"""Point 5 SHAPE template — per-connection SEAM test (the keystone).

test-writer MUST emit a seam test for EVERY connection A → B matching this shape:
- construct REAL block A and REAL block B
- run A with realistic input
- feed A's REAL output into B (no Mock(A), no hand-written fake A payload)
- assert B accepts and runs

Fictional mini-blocks only — not a product fixture.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Type

import pytest
from pydantic import BaseModel, Field, ValidationError


class CapabilityDescriptor(BaseModel):
    provides: list[str] = Field(default_factory=list)
    needs: list[str] = Field(default_factory=list)


def err(block: "Block", status: str, *, reason: str, missing: list[str] | None = None) -> dict[str, Any]:
    return {
        "block": block.name,
        "status": status,
        "reason": reason,
        "missing": missing or [],
    }


class Block(ABC):
    name: ClassVar[str]
    InputModel: ClassVar[Type[BaseModel]]
    OutputModel: ClassVar[Type[BaseModel]]
    capabilities: ClassVar[CapabilityDescriptor]

    @abstractmethod
    async def _run(self, data: BaseModel) -> BaseModel: ...

    async def run(self, raw: dict) -> dict:
        try:
            data = self.InputModel.model_validate(raw)
        except ValidationError as e:
            return err(self, "rejected", reason=str(e))
        out = await self._run(data)
        return self.OutputModel.model_validate(out).model_dump()


# --- fictional upstream A -------------------------------------------------

class UpstreamIn(BaseModel):
    raw: str


class UpstreamOut(BaseModel):
    normalized: str


class ExampleUpstream(Block):
    name = "example_upstream"
    InputModel = UpstreamIn
    OutputModel = UpstreamOut
    capabilities = CapabilityDescriptor(provides=["text.normalized"], needs=[])

    async def _run(self, data: UpstreamIn) -> UpstreamOut:
        return UpstreamOut(normalized=data.raw.strip().lower())


# --- fictional downstream B (consumes A's output shape) -------------------

class DownstreamIn(BaseModel):
    normalized: str


class DownstreamOut(BaseModel):
    token_count: int


class ExampleDownstream(Block):
    name = "example_downstream"
    InputModel = DownstreamIn
    OutputModel = DownstreamOut
    capabilities = CapabilityDescriptor(
        provides=["text.token_count"],
        needs=["text.normalized"],
    )

    async def _run(self, data: DownstreamIn) -> DownstreamOut:
        tokens = [t for t in data.normalized.split() if t]
        return DownstreamOut(token_count=len(tokens))


def registry_compatible(upstream: Block, downstream: Block) -> bool:
    """Point 3 sketch: assembly refuses seams when needs ⊄ provides."""
    return set(downstream.capabilities.needs).issubset(set(upstream.capabilities.provides))


# --- Point 5 seam test (shape) --------------------------------------------

@pytest.mark.asyncio
async def test_seam_upstream_to_downstream_real_handoff():
    """KEYSTONE: real A output feeds real B — never Mock(ExampleUpstream)."""
    a = ExampleUpstream()
    b = ExampleDownstream()

    assert registry_compatible(a, b), "connection registry must accept this seam"

    a_result = await a.run({"raw": "  Hello World  "})
    # Guard: A must have produced a success payload, not an error envelope
    assert "status" not in a_result or a_result.get("status") not in {"rejected", "failed"}

    # REAL handoff — A's output is B's input (schema-compatible fields)
    b_result = await b.run(a_result)
    parsed = DownstreamOut.model_validate(b_result)
    assert parsed.token_count == 2


@pytest.mark.asyncio
async def test_seam_incompatible_needs_are_refused_at_assembly():
    class Lonely(Block):
        name = "lonely"
        InputModel = DownstreamIn
        OutputModel = DownstreamOut
        capabilities = CapabilityDescriptor(provides=[], needs=["text.normalized"])

        async def _run(self, data: DownstreamIn) -> DownstreamOut:
            return DownstreamOut(token_count=0)

    a = ExampleUpstream()
    lonely = Lonely()
    # Upstream provides text.normalized; Lonely needs it — OK.
    # Flip: upstream that provides nothing should fail registry check.
    class EmptyProvider(Block):
        name = "empty"
        InputModel = UpstreamIn
        OutputModel = UpstreamOut
        capabilities = CapabilityDescriptor(provides=[], needs=[])

        async def _run(self, data: UpstreamIn) -> UpstreamOut:
            return UpstreamOut(normalized=data.raw)

    empty = EmptyProvider()
    assert not registry_compatible(empty, lonely)
