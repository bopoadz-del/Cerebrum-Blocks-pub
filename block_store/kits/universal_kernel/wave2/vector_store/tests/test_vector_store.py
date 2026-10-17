"""Tests for the neutral vector store sub-kit."""

import math
from typing import List

import pytest

from block_store.kits.universal_kernel.wave2.vector_store import (
    Chunk,
    PgvectorStore,
    VectorStore,
    VectorStoreError,
)


def _unit_vector(dim: int, index: int) -> List[float]:
    vec = [0.0] * dim
    vec[index] = 1.0
    return vec


def test_upsert_and_search():
    store = VectorStore()
    chunks = [
        Chunk(id="c1", text="alpha", vector=_unit_vector(3, 0)),
        Chunk(id="c2", text="beta", vector=_unit_vector(3, 1)),
    ]
    store.upsert("tenant-1", "project-1", chunks)
    results = store.search("tenant-1", "project-1", _unit_vector(3, 0), top_k=2)
    assert len(results) == 2
    assert results[0].chunk.id == "c1"
    assert pytest.approx(results[0].score, 0.001) == 1.0


def test_tenant_project_isolation():
    store = VectorStore()
    store.upsert("tenant-1", "project-1", [Chunk(id="c1", text="alpha", vector=_unit_vector(3, 0))])
    results = store.search("tenant-2", "project-1", _unit_vector(3, 0))
    assert results == []


def test_empty_store_returns_empty():
    store = VectorStore()
    results = store.search("tenant-1", "project-1", _unit_vector(3, 0))
    assert results == []


def test_filters_restrict_results():
    store = VectorStore()
    chunks = [
        Chunk(id="c1", text="alpha", vector=_unit_vector(3, 0), metadata={"tag": "a"}),
        Chunk(id="c2", text="beta", vector=_unit_vector(3, 0), metadata={"tag": "b"}),
    ]
    store.upsert("tenant-1", "project-1", chunks)
    results = store.search("tenant-1", "project-1", _unit_vector(3, 0), filters={"tag": "a"})
    assert len(results) == 1
    assert results[0].chunk.id == "c1"


def test_dimension_mismatch_raises():
    store = VectorStore()
    store.upsert("tenant-1", "project-1", [Chunk(id="c1", text="alpha", vector=[1.0, 0.0])])
    with pytest.raises(VectorStoreError):
        store.search("tenant-1", "project-1", [1.0, 0.0, 0.0])


def test_pgvector_store_requires_database_url():
    import os

    old = os.environ.pop("DATABASE_URL", None)
    try:
        with pytest.raises(VectorStoreError):
            PgvectorStore()
    finally:
        if old:
            os.environ["DATABASE_URL"] = old
