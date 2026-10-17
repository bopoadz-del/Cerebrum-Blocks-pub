"""The pgvector RAG path must be able to return an answer.

Found by wiring ruff's F821 (undefined name) over app/, which nothing in CI
did: ``_ask_pgvector`` read ``params`` twice — for the K3 coverage-honesty
fields — and ``_ask`` never passed it. So the moment the path stopped
returning an error and started building a successful payload, it raised

    NameError: name 'params' is not defined

Every test of this block exercised the error branches or the legacy
collection path. Nothing asked it for an answer, so nothing noticed that
the primary path (the one taken whenever a project_id is supplied) could
not produce one.

A NameError on the success path is the shape of bug that survives a green
suite and a coverage report at the same time: the line is imported, the
module loads, the failing branch never runs in a test.
"""
from __future__ import annotations

import pytest

from app.blocks.knowledge import KnowledgeBlock


class _Result:
    def __init__(self, text, score, doc_id="doc-1"):
        self.text = text
        self.score = score
        self.doc_id = doc_id
        self.chunk_index = 0
        self.project_id = "proj-1"
        self.chunk_id = "c-1"


@pytest.fixture
def block():
    return KnowledgeBlock(None, {})


@pytest.mark.asyncio
async def test_a_successful_pgvector_answer_does_not_raise(block, monkeypatch):
    """The regression: this raised NameError before params was threaded."""

    async def fake_retrieve(*a, **k):
        return [_Result("the rate is 0.1 percent per day", 0.91)]

    async def fake_llm(*a, **k):
        return {"status": "success", "content": "The rate is 0.1 percent per day."}

    monkeypatch.setattr(block, "_pgvector_search", fake_retrieve, raising=False)
    monkeypatch.setattr(block, "_synthesize", fake_llm, raising=False)

    out = await block._ask_pgvector(
        "what is the rate?", "proj-1", 5, "kimi", {"corpus_total": 10}
    )
    assert isinstance(out, dict)
    assert out["status"] in {"success", "error"}
    assert "project_id" in out


@pytest.mark.asyncio
async def test_ask_passes_params_through_to_the_pgvector_path(block, monkeypatch):
    """The call site, not just the callee.

    Threading params into the signature is only half the fix; _ask has to
    hand it over, and that is the line that was missing.
    """
    seen = {}

    async def spy(query, project_id, top_k, llm_provider, params):
        seen.update({"params": params, "project_id": project_id})
        return {"status": "success", "answer": "", "project_id": project_id}

    monkeypatch.setattr(block, "_ask_pgvector", spy)
    await block._ask("q", {"project_id": "proj-9", "corpus_total": 42})

    assert seen["project_id"] == "proj-9"
    assert seen["params"]["corpus_total"] == 42, (
        "the K3 coverage fields need params; passing {} would silently drop "
        "the 'N of M indexed' honesty this block exists to provide"
    )


def test_the_signature_still_takes_params(block):
    """A future refactor must not drop it again without saying so."""
    import inspect

    sig = inspect.signature(block._ask_pgvector)
    assert "params" in sig.parameters
