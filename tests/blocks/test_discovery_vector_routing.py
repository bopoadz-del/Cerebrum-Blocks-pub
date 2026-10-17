"""Discovery routes search/recommend through the wired vector block.

The vector path runs only when the vector dep carries a REAL embedder
(dummy md5-hash embeddings produce ~zero cosine between different texts —
routing through them would silently empty results). The response names
which path ran; there is no silent substitution either way.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from app.blocks.discovery import DiscoveryBlock


class _FakeVector:
    """Stands in for the vector block: records adds, returns canned hits."""

    def __init__(self, real_embedder: bool = True):
        self._embeddings_func = object() if real_embedder else None
        self.added: List[Dict[str, Any]] = []
        self.results: List[Dict[str, Any]] = []

    async def process(self, data: Dict, params: Dict = None) -> Dict:
        action = (params or {}).get("action")
        if action == "add":
            self.added.append(dict(data))
            return {"added": True, "id": data["id"], "vector_dim": 384}
        if action == "search":
            return {
                "query": data.get("query"),
                "results": self.results,
                "total_found": len(self.results),
            }
        raise AssertionError(f"unexpected action {action}")


def _init(block: DiscoveryBlock) -> DiscoveryBlock:
    asyncio.run(block._legacy_initialize())
    return block


def _run(block: DiscoveryBlock, action: str, **data) -> Dict[str, Any]:
    return asyncio.run(block.process(dict(data), params={"action": action}))


def _pdf_profile_id() -> str:
    return "pdf"


def test_index_block_into_wired_vector():
    block = DiscoveryBlock()
    fake = _FakeVector(real_embedder=True)
    block.wire("vector", fake)
    out = _run(
        block,
        "index_block",
        profile={
            "block_id": "custom_block",
            "name": "Custom",
            "description": "custom thing",
            "tags": ["x"],
            "use_cases": ["y"],
        },
    )
    assert out["indexed"] is True
    assert out["vector_indexed"] is True
    assert fake.added and fake.added[-1]["id"] == "block:custom_block"
    assert "Custom" in fake.added[-1]["text"]


def test_index_block_without_vector_is_honest():
    block = DiscoveryBlock()
    out = _run(
        block,
        "index_block",
        profile={"block_id": "solo", "name": "Solo", "description": ""},
    )
    assert out["indexed"] is True
    assert out["vector_indexed"] is False


def test_semantic_search_uses_vector_when_wired():
    block = _init(DiscoveryBlock())
    fake = _FakeVector(real_embedder=True)
    block.wire("vector", fake)
    fake.results = [
        {"id": f"block:{_pdf_profile_id()}", "score": 0.91, "text": "pdf...", "metadata": {}}
    ]
    out = _run(block, "search_blocks", query="extract tables from documents")
    assert out["via"] == "vector"
    assert out["results"][0]["block_id"] == "pdf"
    assert out["results"][0]["score"] == 0.91


def test_semantic_search_falls_back_to_keyword_without_real_embedder():
    block = _init(DiscoveryBlock())
    fake = _FakeVector(real_embedder=False)  # wired, but dummy embeddings
    block.wire("vector", fake)
    out = _run(block, "search_blocks", query="pdf extraction")
    assert out["via"] == "keyword"
    assert any(r["block_id"] == "pdf" for r in out["results"])


def test_semantic_search_keyword_when_unwired():
    block = _init(DiscoveryBlock())
    out = _run(block, "search_blocks", query="pdf extraction")
    assert out["via"] == "keyword"
    assert any(r["block_id"] == "pdf" for r in out["results"])


def test_semantic_search_vector_applies_filters():
    block = _init(DiscoveryBlock())
    fake = _FakeVector(real_embedder=True)
    block.wire("vector", fake)
    fake.results = [
        {"id": "block:pdf", "score": 0.9, "text": "pdf...", "metadata": {}},
        {"id": "block:webhook", "score": 0.8, "text": "wh...", "metadata": {}},
    ]
    out = _run(
        block,
        "search_blocks",
        query="anything",
        filters={"layer": 2, "tag": "pdf"},
    )
    assert out["via"] == "vector"
    ids = [r["block_id"] for r in out["results"]]
    assert ids == ["pdf"]


def test_recommend_stack_uses_vector_for_goal():
    block = _init(DiscoveryBlock())
    fake = _FakeVector(real_embedder=True)
    block.wire("vector", fake)
    fake.results = [
        {"id": "block:pdf", "score": 0.85, "text": "pdf...", "metadata": {}}
    ]
    out = _run(block, "recommend_for_project", goal="analyze construction documents")
    assert out["goal_match"] == "vector"
    assert any(
        "(vector)" in reason
        for rec in out["recommendations"]
        for reason in rec["reasons"]
    )


def test_recommend_stack_keyword_goal_without_vector():
    block = _init(DiscoveryBlock())
    out = _run(block, "recommend_for_project", goal="document analysis")
    assert out["goal_match"] == "keyword"
