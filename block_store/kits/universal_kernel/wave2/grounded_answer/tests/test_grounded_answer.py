"""Tests for the neutral grounded answerer sub-kit."""

from block_store.kits.universal_kernel.wave2.embedding_provider import HashEmbeddingProvider
from block_store.kits.universal_kernel.wave2.grounded_answer import GroundedAnswerer
from block_store.kits.universal_kernel.wave2.llm_provider import get_provider
from block_store.kits.universal_kernel.wave2.vector_store import Chunk, VectorStore


def _make_store():
    store = VectorStore()
    embedder = HashEmbeddingProvider()
    chunks = [
        Chunk(
            id="c1",
            text="The capital of France is Paris.",
            vector=embedder.embed(["France capital"])["vectors"][0],
            metadata={"source_class": "official_guidance"},
        ),
        Chunk(
            id="c2",
            text="Berlin is the capital of Germany.",
            vector=embedder.embed(["Germany capital"])["vectors"][0],
            metadata={"source_class": "official_guidance"},
        ),
    ]
    store.upsert("tenant-1", "project-1", chunks)
    return store


def test_answer_returns_grounded_response():
    store = _make_store()
    embedder = HashEmbeddingProvider()
    llm = get_provider("stub")
    answerer = GroundedAnswerer(store, llm, embed_fn=lambda text: embedder.embed([text])["vectors"][0])
    result = answerer.answer("tenant-1", "project-1", "What is the capital of France?")
    assert "Stub answer" in result["answer"]
    assert result["honesty"] == "grounded"
    assert len(result["citations"]) > 0
    assert result["citations"][0]["chunk_id"] == "c1"
    assert result["citations"][0]["source_class"] == "official_guidance"
    assert result["source_class_rendered"] is True


def test_insufficient_sources():
    store = VectorStore()
    embedder = HashEmbeddingProvider()
    llm = get_provider("stub")
    answerer = GroundedAnswerer(store, llm, embed_fn=lambda text: embedder.embed([text])["vectors"][0])
    result = answerer.answer("tenant-1", "project-1", "What is the capital of Mars?")
    assert result["answer"] == "Insufficient sources."
    assert result["honesty"] == "insufficient_sources"
    assert result["citations"] == []


class _DoesNotExistLLM:
    """Planted: answers with the forbidden claim so K3 can refuse it."""

    def complete(self, prompt, **kwargs):
        class _C:
            text = "that clause does-not-exist in the corpus"
        return _C()


def test_coverage_line_is_n_of_m_indexed():
    store = _make_store()
    embedder = HashEmbeddingProvider()
    llm = get_provider("stub")
    answerer = GroundedAnswerer(store, llm, embed_fn=lambda text: embedder.embed([text])["vectors"][0])
    result = answerer.answer(
        "tenant-1", "project-1", "What is the capital of France?", corpus_total=10
    )
    assert result["coverage_line"] == "2 of 10 indexed"
    assert result["honesty"] == "grounded"


def test_does_not_exist_is_refused_below_full_coverage():
    store = _make_store()
    embedder = HashEmbeddingProvider()
    answerer = GroundedAnswerer(
        store,
        _DoesNotExistLLM(),
        embed_fn=lambda text: embedder.embed([text])["vectors"][0],
    )
    result = answerer.answer(
        "tenant-1", "project-1", "Is there a 2026 rate table?", corpus_total=10
    )
    assert result["honesty"] == "refused"
    assert "does-not-exist" in result["reason"]


def test_unclassified_chunks_are_refused():
    store = VectorStore()
    embedder = HashEmbeddingProvider()
    store.upsert(
        "tenant-1",
        "project-1",
        [
            Chunk(
                id="bare",
                text="The capital of France is Paris.",
                vector=embedder.embed(["France capital"])["vectors"][0],
                metadata={},
            )
        ],
    )
    llm = get_provider("stub")
    answerer = GroundedAnswerer(store, llm, embed_fn=lambda text: embedder.embed([text])["vectors"][0])
    result = answerer.answer("tenant-1", "project-1", "What is the capital of France?")
    assert result["honesty"] == "refused"
    assert "source_class" in result["reason"]


def test_no_cross_tenant_borrowing():
    store = _make_store()
    embedder = HashEmbeddingProvider()
    llm = get_provider("stub")
    answerer = GroundedAnswerer(store, llm, embed_fn=lambda text: embedder.embed([text])["vectors"][0])
    result = answerer.answer("tenant-2", "project-1", "What is the capital of France?")
    assert result["honesty"] == "insufficient_sources"
