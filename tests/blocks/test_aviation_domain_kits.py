"""Tests for aviation domain kit blocks (PSS, revenue, loyalty, cargo, CX)."""

import pytest

from app.blocks.aviation_pss_kit import AviationPssKitBlock
from app.blocks.aviation_revenue_kit import AviationRevenueKitBlock
from app.blocks.aviation_loyalty_kit import AviationLoyaltyKitBlock
from app.blocks.aviation_cargo_kit import AviationCargoKitBlock
from app.blocks.aviation_cx_kit import AviationCxKitBlock
from app.blocks.aviation_grounding_gate import AviationGroundingGateBlock


class _FakeVectorSearch:
    def __init__(self, results):
        self.results = results

    async def process(self, input_data, params=None):
        return {"results": self.results}


class _FakeChat:
    def __init__(self, answer):
        self.answer = answer

    async def process(self, input_data, params=None):
        return {"text": self.answer}


@pytest.fixture
def grounded_citations():
    return [
        {"text": "Business class fare is $2,500 round trip.", "id": "doc1"},
        {"text": "Economy fare is 1,200 SAR.", "id": "doc2"},
    ]


@pytest.fixture
def fabricated_citations():
    return [
        {"text": "Fares are subject to seasonal pricing.", "id": "doc1"},
    ]


@pytest.mark.asyncio
async def test_pss_kit_returns_grounded_answer(grounded_citations):
    block = AviationPssKitBlock()
    block.wire("vector_search", _FakeVectorSearch(grounded_citations))
    block.wire("chat", _FakeChat("The business class fare is $2,500."))
    block.wire("aviation_grounding_gate", AviationGroundingGateBlock())

    result = await block.process({
        "query": "What is the business class fare?",
        "project_id": "proj_1",
    })

    assert result["status"] == "success"
    assert result["domain"] == "pss"
    assert result["verdict"] == "pass"
    assert result["answer"] is not None
    assert any("$2,500" in c["text"] for c in result["citations"])


@pytest.mark.asyncio
async def test_pss_kit_blocks_fabricated_fare(fabricated_citations):
    block = AviationPssKitBlock()
    block.wire("vector_search", _FakeVectorSearch(fabricated_citations))
    block.wire("chat", _FakeChat("The fare is 999 SAR."))
    block.wire("aviation_grounding_gate", AviationGroundingGateBlock())

    result = await block.process({
        "query": "What is the fare?",
        "project_id": "proj_1",
    })

    assert result["domain"] == "pss"
    assert result["verdict"] == "block"
    assert result["answer"] is None
    assert result["blocked_reason"] is not None


@pytest.mark.asyncio
async def test_revenue_kit_returns_grounded_answer():
    citations = [
        {"text": "Average load factor in Q1 was 82%.", "id": "doc1"},
    ]
    block = AviationRevenueKitBlock()
    block.wire("vector_search", _FakeVectorSearch(citations))
    block.wire("chat", _FakeChat("The average load factor in Q1 was 82%."))
    block.wire("aviation_grounding_gate", AviationGroundingGateBlock())

    result = await block.process({
        "query": "What was the Q1 load factor?",
        "project_id": "proj_1",
    })

    assert result["status"] == "success"
    assert result["domain"] == "revenue"
    assert result["verdict"] == "pass"
    assert result["analysis_type"] == "read-only"


@pytest.mark.asyncio
async def test_revenue_kit_adds_decision_disclaimer():
    citations = [
        {"text": "Average load factor in Q1 was 82%.", "id": "doc1"},
    ]
    block = AviationRevenueKitBlock()
    block.wire("vector_search", _FakeVectorSearch(citations))
    block.wire("chat", _FakeChat("The average load factor in Q1 was 82%."))
    block.wire("aviation_grounding_gate", AviationGroundingGateBlock())

    result = await block.process({
        "query": "What was the Q1 load factor?",
        "project_id": "proj_1",
    })

    assert any("pricing decision" in d.lower() for d in result["disclaimers"])


@pytest.mark.asyncio
async def test_loyalty_kit_returns_grounded_answer():
    citations = [
        {"text": "Gold tier requires 50,000 miles.", "id": "doc1"},
    ]
    block = AviationLoyaltyKitBlock()
    block.wire("vector_search", _FakeVectorSearch(citations))
    block.wire("chat", _FakeChat("Gold tier requires 50,000 miles."))
    block.wire("aviation_grounding_gate", AviationGroundingGateBlock())

    result = await block.process({
        "query": "How many miles for Gold tier?",
        "project_id": "proj_1",
    })

    assert result["status"] == "success"
    assert result["domain"] == "loyalty"
    assert result["verdict"] == "pass"


@pytest.mark.asyncio
async def test_cargo_kit_applies_safety_critical_gate():
    citations = [
        {"text": "Maximum pallet weight is 3,000 kg.", "id": "doc1"},
    ]
    block = AviationCargoKitBlock()
    block.wire("vector_search", _FakeVectorSearch(citations))
    block.wire("chat", _FakeChat("Maximum pallet weight is 3,000 kg."))
    block.wire("aviation_grounding_gate", AviationGroundingGateBlock())

    result = await block.process({
        "query": "What is the maximum pallet weight?",
        "project_id": "proj_1",
    })

    assert result["status"] == "success"
    assert result["domain"] == "cargo"
    assert result["verdict"] == "pass"
    assert any("safety-critical" in d.lower() for d in result["disclaimers"])


@pytest.mark.asyncio
async def test_cargo_kit_blocks_ungrounded_weight():
    citations = [
        {"text": "Cargo handling procedures must be followed.", "id": "doc1"},
    ]
    block = AviationCargoKitBlock()
    block.wire("vector_search", _FakeVectorSearch(citations))
    block.wire("chat", _FakeChat("Maximum pallet weight is 5,000 kg."))
    block.wire("aviation_grounding_gate", AviationGroundingGateBlock())

    result = await block.process({
        "query": "What is the maximum pallet weight?",
        "project_id": "proj_1",
    })

    assert result["domain"] == "cargo"
    assert result["verdict"] == "block"
    assert result["answer"] is None


@pytest.mark.asyncio
async def test_cx_kit_returns_grounded_answer():
    citations = [
        {"text": "Compensation for delays over 3 hours is 400 SAR.", "id": "doc1"},
    ]
    block = AviationCxKitBlock()
    block.wire("vector_search", _FakeVectorSearch(citations))
    block.wire("chat", _FakeChat("Compensation for delays over 3 hours is 400 SAR."))
    block.wire("aviation_grounding_gate", AviationGroundingGateBlock())

    result = await block.process({
        "query": "What is the delay compensation?",
        "project_id": "proj_1",
    })

    assert result["status"] == "success"
    assert result["domain"] == "cx"
    assert result["verdict"] == "pass"


@pytest.mark.asyncio
async def test_domain_kit_requires_project_id():
    block = AviationPssKitBlock()
    result = await block.process({"query": "What is the fare?"})
    assert result["status"] == "error"
    assert "project_id" in result["blocked_reason"]
