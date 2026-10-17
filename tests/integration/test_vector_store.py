"""Tests for the pgvector-backed vector_store module."""

import os
import uuid

import pytest
from dotenv import load_dotenv

load_dotenv()

from app.core import vector_store


pytestmark = pytest.mark.skipif(
    os.getenv("DATABASE_URL") is None,
    reason="DATABASE_URL not set; skipping vector store tests",
)


@pytest.fixture
async def pool():
    """Ensure the vector store pool is initialized for the test loop.

    The global pool may already be bound to the running uvicorn loop, so we
    reset the module-level reference and create a fresh pool for the tests.
    """
    vector_store._pool = None
    await vector_store.init_pool()
    yield vector_store._pool
    await vector_store.close_pool()
    vector_store._pool = None


async def _cleanup_tenant(tenant_id: str):
    """Remove all test data for a tenant."""
    if vector_store._pool is None:
        return
    async with vector_store._pool.acquire() as conn:
        await conn.execute(
            """
            DELETE FROM chunks WHERE project_id IN (
                SELECT id FROM projects WHERE tenant_id = $1
            )
            """,
            tenant_id,
        )
        await conn.execute(
            "DELETE FROM ingestion_jobs WHERE document_id IN (SELECT id FROM documents WHERE project_id IN (SELECT id FROM projects WHERE tenant_id = $1))",
            tenant_id,
        )
        await conn.execute(
            "DELETE FROM documents WHERE project_id IN (SELECT id FROM projects WHERE tenant_id = $1)",
            tenant_id,
        )
        await conn.execute("DELETE FROM projects WHERE tenant_id = $1", tenant_id)


@pytest.mark.asyncio
async def test_ensure_project_is_idempotent(pool):
    tenant = f"test-{uuid.uuid4().hex[:8]}"
    project1 = await vector_store.ensure_project(tenant, name="demo")
    project2 = await vector_store.ensure_project(tenant, name="demo")
    assert project1["id"] == project2["id"]
    assert project1["tenant_id"] == tenant
    await _cleanup_tenant(tenant)


@pytest.mark.asyncio
async def test_create_document_and_search(pool):
    tenant = f"test-{uuid.uuid4().hex[:8]}"
    project = await vector_store.ensure_project(tenant, name="demo")
    doc = await vector_store.create_document(
        project["id"],
        "Planted Truth",
        "/docs/truth.txt",
        {"author": "test-suite"},
    )
    assert doc is not None
    assert doc["title"] == "Planted Truth"
    assert doc["doc_metadata"]["author"] == "test-suite"

    chunks = [
        {"content": "The aviation fuel capacity of the A350-900 is 138,000 litres.", "metadata": {"page": 1}},
        {"content": "This sentence exists only as distractor text.", "metadata": {"page": 2}},
    ]
    inserted = await vector_store.add_chunks(doc["id"], chunks)
    assert inserted == 2

    results = await vector_store.search_vectors(
        project["id"], "A350-900 fuel capacity litres", top_k=3, threshold=0.2
    )
    assert len(results) >= 1
    top = results[0]
    assert "fuel capacity" in top["content"].lower()
    assert top["metadata"].get("page") == 1
    assert top["score"] > 0.0

    await _cleanup_tenant(tenant)


@pytest.mark.asyncio
async def test_cross_tenant_isolation(pool):
    tenant_a = f"test-a-{uuid.uuid4().hex[:8]}"
    tenant_b = f"test-b-{uuid.uuid4().hex[:8]}"

    project_a = await vector_store.ensure_project(tenant_a, name="isolated")
    project_b = await vector_store.ensure_project(tenant_b, name="isolated")

    doc_b = await vector_store.create_document(
        project_b["id"], "Secret Doc", "/docs/secret.txt", {}
    )
    await vector_store.add_chunks(
        doc_b["id"], [{"content": "This chunk belongs to tenant B.", "metadata": {}}]
    )

    results = await vector_store.search_vectors(
        project_a["id"], "tenant B chunk", top_k=5, threshold=0.0
    )
    assert all(r["document_id"] != str(doc_b["id"]) for r in results)

    await _cleanup_tenant(tenant_a)
    await _cleanup_tenant(tenant_b)


@pytest.mark.asyncio
async def test_hybrid_search_ranks_keyword_matches(pool):
    tenant = f"test-{uuid.uuid4().hex[:8]}"
    project = await vector_store.ensure_project(tenant, name="hybrid")
    doc = await vector_store.create_document(project["id"], "Hybrid Doc", "/docs/h.txt", {})
    await vector_store.add_chunks(
        doc["id"],
        [
            {"content": "The quick brown fox jumps over the lazy dog.", "metadata": {}},
            {"content": "Kubernetes is a container orchestration platform.", "metadata": {}},
        ],
    )

    results = await vector_store.hybrid_search(
        project["id"], "container orchestration", top_k=2, threshold=0.1
    )
    assert len(results) >= 1
    assert "kubernetes" in results[0]["content"].lower()

    await _cleanup_tenant(tenant)
