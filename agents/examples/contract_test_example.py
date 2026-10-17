"""Point 4 SHAPE template — per-block contract test.

test-writer MUST emit tests matching this shape for every Block:
- invalid input → honest rejected envelope
- valid input → OutputModel-honoring result
- schema IS the test source (derive fixtures from InputModel/OutputModel)

Fictional mini-blocks only — not a product fixture.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Type

import pytest
from pydantic import BaseModel, ValidationError, Field


# --- fictional Block surface (mirrors Pillar A Point 2) -------------------

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
        # Point 1: fail loud at THIS block if output is off-contract
        return self.OutputModel.model_validate(out).model_dump()


class ExampleEchoIn(BaseModel):
    text: str


class ExampleEchoOut(BaseModel):
    text: str
    length: int


class ExampleEcho(Block):
    name = "example_echo"
    InputModel = ExampleEchoIn
    OutputModel = ExampleEchoOut
    capabilities = CapabilityDescriptor(provides=["text.echo"], needs=[])

    async def _run(self, data: ExampleEchoIn) -> ExampleEchoOut:
        return ExampleEchoOut(text=data.text, length=len(data.text))


# --- Point 4 contract tests (shape) ---------------------------------------

@pytest.mark.asyncio
async def test_contract_rejects_invalid_input():
    block = ExampleEcho()
    result = await block.run({"text": 123})  # wrong type
    assert result["status"] == "rejected"
    assert result["block"] == "example_echo"
    assert "reason" in result


@pytest.mark.asyncio
async def test_contract_output_matches_output_model():
    block = ExampleEcho()
    result = await block.run({"text": "ok"})
    # Must validate as OutputModel — schema is the oracle
    parsed = ExampleEchoOut.model_validate(result)
    assert parsed.text == "ok"
    assert parsed.length == 2


@pytest.mark.asyncio
async def test_contract_output_validation_fails_at_guilty_block(monkeypatch):
    block = ExampleEcho()

    async def _bad(_data: ExampleEchoIn):
        return {"text": "ok"}  # missing length — off-contract

    monkeypatch.setattr(block, "_run", _bad)
    with pytest.raises(ValidationError):
        await block.run({"text": "ok"})
