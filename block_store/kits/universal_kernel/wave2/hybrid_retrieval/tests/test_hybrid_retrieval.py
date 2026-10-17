"""Tests for the neutral hybrid retrieval sub-kit."""

import math
from typing import List

import pytest

from block_store.kits.universal_kernel.wave2.hybrid_retrieval import (
    RetrievalError,
    hybrid_search,
    lexical_rank,
)
from block_store.kits.universal_kernel.wave2.vector_store import Chunk, VectorStore


def _unit_vector(dim: int, index: int) -> List[float]:
    vec = [0.0] * dim
    vec[index] = 1.0
    return vec


def test_lexical_rank_token_overlap():
    chunks = [
        Chunk(id="c1", text="the quick brown fox", vector=[]),
        Chunk(id="c2", text="lazy dog sleeps", vector=[]),
    ]
    ranked = lexical_rank("quick fox", chunks)
    assert ranked[0][1].id == "c1"


def test_hybrid_search_no_sources():
    store = VectorStore()
    result = hybrid_search(
        store,
        "tenant-1",
        "project-1",
        "something",
        [1.0, 0.0, 0.0],
        top_k=3,
    )
    assert result["results"] == []
    assert result["honesty"] == "no_sources"


def test_hybrid_search_fuses_results():
    store = VectorStore()
    chunks = [
        Chunk(id="c1", text="alpha beta gamma", vector=_unit_vector(3, 0)),
        Chunk(id="c2", text="alpha delta echo", vector=_unit_vector(3, 1)),
        Chunk(id="c3", text="beta foxtrot", vector=_unit_vector(3, 2)),
    ]
    store.upsert("tenant-1", "project-1", chunks)
    result = hybrid_search(
        store,
        "tenant-1",
        "project-1",
        "alpha",
        _unit_vector(3, 0),
        top_k=2,
    )
    assert len(result["results"]) == 2
    assert result["honesty"] == "hybrid"
    assert all(hasattr(r, "score") and r.chunk for r in result["results"])


def test_empty_query_raises():
    store = VectorStore()
    with pytest.raises(RetrievalError):
        hybrid_search(store, "tenant-1", "project-1", "", [1.0])
