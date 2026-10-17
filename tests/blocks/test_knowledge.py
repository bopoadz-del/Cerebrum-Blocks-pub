"""Tests for RAG Knowledge Block v2."""

import pytest
from app.blocks import KnowledgeBlock


@pytest.fixture
def knowledge_block():
    return KnowledgeBlock()


@pytest.mark.asyncio
async def test_knowledge_block_execute_structure(knowledge_block):
    result = await knowledge_block.execute(
        "What is Cerebrum?",
        {"action": "ask", "top_k": 3},
    )
    assert "block" in result
    assert result["block"] == "knowledge"
    assert "request_id" in result
    assert "status" in result
    assert "result" in result
    assert "confidence" in result


@pytest.mark.asyncio
async def test_knowledge_block_metadata(knowledge_block):
    assert knowledge_block.name == "knowledge"
    assert knowledge_block.config.version == "2.0.0"
    assert knowledge_block.config.requires_api_key == False


@pytest.mark.asyncio
async def test_knowledge_search_only(knowledge_block):
    result = await knowledge_block.execute(
        "test query",
        {"action": "search", "top_k": 2},
    )
    inner = result.get("result", result)
    assert inner.get("status") == "success"
    assert "results" in inner or "error" in inner


@pytest.mark.asyncio
async def test_knowledge_summarize(knowledge_block):
    result = await knowledge_block.execute(
        None,
        {"action": "summarize", "collection": "test"},
    )
    inner = result.get("result", result)
    assert inner.get("status") == "success"
    assert "summary" in inner


@pytest.mark.asyncio
async def test_knowledge_confidence(knowledge_block):
    chunks = [
        {"score": 0.95},
        {"score": 0.85},
    ]
    conf = knowledge_block._compute_confidence(chunks)
    assert conf == 0.9

    empty = []
    assert knowledge_block._compute_confidence(empty) == 0.0


@pytest.mark.asyncio
async def test_knowledge_extract_citations(knowledge_block):
    source_map = {
        "Source 1": {"id": "doc1", "collection": "c1"},
        "Source 2": {"id": "doc2", "collection": "c1"},
    }
    answer = "According to [Source 1], this is true."
    cited = knowledge_block._extract_citations(answer, source_map)
    assert len(cited) == 1
    assert cited[0]["id"] == "doc1"
