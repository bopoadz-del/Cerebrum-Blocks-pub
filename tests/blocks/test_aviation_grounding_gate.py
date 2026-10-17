"""Tests for aviation_grounding_gate block scope enforcement."""

import pytest

from app.blocks.aviation_grounding_gate import AviationGroundingGateBlock


@pytest.fixture
def gate():
    return AviationGroundingGateBlock(config={})


@pytest.mark.asyncio
async def test_gate_passes_when_figure_is_cited(gate):
    result = await gate.process({
        "query": "What is the checked baggage allowance?",
        "answer": "Passengers may check up to 30 kg of baggage.",
        "citations": [
            {"text": "Checked baggage allowance is 30 kg per passenger on all routes."},
        ],
        "query_type": "weight",
    })
    assert result["status"] == "success"
    assert result["verdict"] == "pass"
    assert "Verify before operational use" in " ".join(result["required_disclaimers"])


@pytest.mark.asyncio
async def test_gate_blocks_fabricated_fare(gate):
    result = await gate.process({
        "query": "What is the fare from RUH to JED?",
        "answer": "The fare is 1,250 SAR.",
        "citations": [
            {"text": "Fares are subject to availability and seasonal pricing."},
        ],
        "query_type": "fare",
    })
    assert result["status"] == "success"
    assert result["verdict"] == "block"
    assert result["allowed_response"] is None
    assert "1250" in result["blocked_reason"]


@pytest.mark.asyncio
async def test_gate_blocks_weight_without_citation(gate):
    result = await gate.process({
        "query": "What is the maximum takeoff weight?",
        "answer": "The MTOW is 78,000 kg.",
        "citations": [],
        "query_type": "weight",
    })
    assert result["verdict"] == "block"


@pytest.mark.asyncio
async def test_gate_flags_weak_citation(gate):
    result = await gate.process({
        "query": "Fuel burn per hour?",
        "answer": "Fuel burn is approximately 2,400 kg per hour.",
        "citations": [
            {"text": "The aircraft consumes fuel during cruise."},
        ],
        "query_type": "fuel",
    })
    # Value not present, unit context absent -> block (score 0).
    assert result["verdict"] == "block"


@pytest.mark.asyncio
async def test_gate_passes_currency_with_symbol(gate):
    result = await gate.process({
        "query": "What is the business class fare?",
        "answer": "Business class is $2,500.",
        "citations": [
            {"text": "Business class fare: $2,500 round trip."},
        ],
        "query_type": "fare",
    })
    assert result["verdict"] == "pass"


@pytest.mark.asyncio
async def test_gate_blocks_when_numeric_answer_expected_but_missing(gate):
    result = await gate.process({
        "query": "How much does the ticket cost?",
        "answer": "Tickets are available on our website.",
        "citations": [
            {"text": "Tickets are available on our website."},
        ],
        "query_type": "fare",
    })
    assert result["verdict"] == "block"


@pytest.mark.asyncio
async def test_gate_does_not_mutate_answer_text(gate):
    answer = "The allowance is 30 kg."
    result = await gate.process({
        "query": "Allowance?",
        "answer": answer,
        "citations": [{"text": "Allowance is 30 kg."}],
        "query_type": "weight",
    })
    assert result["verdict"] == "pass"
    assert result["allowed_response"].startswith(answer)
    assert "30 kg" in result["allowed_response"]
    # The gate must not invent content inside the answer.
    assert "citation" not in result["allowed_response"].split("\n\n")[0]


@pytest.mark.asyncio
async def test_gate_does_not_alter_numeric_value(gate):
    result = await gate.process({
        "query": "Baggage allowance?",
        "answer": "30 kg.",
        "citations": [{"text": "30 kg allowance"}],
        "query_type": "weight",
    })
    assert "30 kg" in result["allowed_response"]
    assert "25 kg" not in result["allowed_response"]
