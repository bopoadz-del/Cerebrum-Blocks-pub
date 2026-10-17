"""End-to-end RAG ingestion + retrieval tests.

Planted-truth style: a document with a known fact is ingested, then we assert
that a question about that fact returns the fact and a citation. We also assert
that an unrelated question does not fabricate an answer from the same corpus.
"""

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app

pytestmark = pytest.mark.skipif(
    os.getenv("DATABASE_URL") is None,
    reason="DATABASE_URL not set; skipping RAG ingestion tests",
)

_PLANTED_FACT = (
    "The aviation fuel capacity of the Airbus A350-900 is 138,000 litres. "
    "The A350-1000 has a fuel capacity of 159,000 litres."
)


def _unique_tenant() -> str:
    return f"rag-test-{uuid.uuid4().hex[:8]}"


def _auth_client() -> TestClient:
    return TestClient(app, headers={"Authorization": "Bearer cb_dev_key"})


def test_ingest_text_then_retrieve_cited_fact():
    """A planted fact survives the full ingest→chunk→embed→retrieve pipeline."""
    tenant = _unique_tenant()

    with _auth_client() as client:
        ingest_resp = client.post(
            "/ingestion/text",
            json={
                "tenant_id": tenant,
                "project_name": "planted-truth",
                "title": "Aviation facts",
                "text": _PLANTED_FACT,
            },
        )
        assert ingest_resp.status_code == 200, ingest_resp.text
        ingest = ingest_resp.json()
        assert ingest["status"] == "success"
        assert ingest["chunks"] > 0
        project_id = ingest["project_id"]

        ask_resp = client.post(
            "/knowledge/ask",
            json={
                "question": "What is the fuel capacity of the A350-900?",
                "project_id": project_id,
                "top_k": 3,
            },
        )
        assert ask_resp.status_code == 200, ask_resp.text
        answer = ask_resp.json()

    assert answer["status"] == "success"
    assert "138,000" in answer["answer"], f"Planted fact missing from answer: {answer}"
    assert answer.get("chunks_retrieved", 0) >= 1
    sources = answer.get("sources", [])
    assert len(sources) >= 1
    assert all(s.get("chunk_id") for s in sources)
    assert any(s.get("score", 0) > 0 for s in sources)


def test_unsourced_query_returns_honest_empty_answer():
    """A question with no support in the corpus must not fabricate."""
    tenant = _unique_tenant()

    with _auth_client() as client:
        ingest_resp = client.post(
            "/ingestion/text",
            json={
                "tenant_id": tenant,
                "project_name": "planted-truth",
                "title": "Aviation facts",
                "text": _PLANTED_FACT,
            },
        )
        assert ingest_resp.status_code == 200, ingest_resp.text
        project_id = ingest_resp.json()["project_id"]

        ask_resp = client.post(
            "/knowledge/ask",
            json={
                "question": "What is the maximum take-off weight of the Boeing 777X?",
                "project_id": project_id,
                "top_k": 3,
            },
        )
        assert ask_resp.status_code == 200, ask_resp.text
        answer = ask_resp.json()

    assert answer["status"] == "success"
    # Either no chunks were retrieved or the answer admits it has no info.
    assert (
        answer.get("chunks_retrieved", 0) == 0
        or "don't have" in answer["answer"].lower()
        or "no relevant" in answer["answer"].lower()
    ), f"Unsourced query fabricated an answer: {answer}"
