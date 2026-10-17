"""End-to-end demo flows — the stranger, encoded.

Boots the real app (TestClient) and asserts user-visible outcomes for the
documented Quick-Start flows. Infra-heavy flows (RAG over pgvector) gate on
DATABASE_URL exactly like the rest of the suite; everything else runs cold.

  B2  health 200
  B4  register a block, invoke it, get a typed result
  B5  tenant isolation (covered in depth by tests/core/test_two_tenant_isolation)
  B3  ingest -> RAG query -> cited answer   (needs DATABASE_URL)
"""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app


def _client() -> TestClient:
    return TestClient(app, headers={"Authorization": "Bearer cb_dev_key"})


# ── B2: health ──────────────────────────────────────────────────────────────
def test_b2_health_and_readiness():
    with TestClient(app) as c:  # health is unauthenticated
        h = c.get("/health")
        assert h.status_code == 200
        assert h.json().get("status") == "ok"
        r = c.get("/ready")
        assert r.status_code in (200, 503)  # 503 only if a real dependency is down
        assert "status" in r.json()


# ── B4: register a block, invoke it, typed result ───────────────────────────
def test_b4_block_is_registered_and_invocable():
    with _client() as c:
        # The block registry is populated at boot; `validation` is a pure,
        # infra-free block. Invoke it and assert a typed (dict) result.
        resp = c.post(
            "/execute",
            json={
                "block": "validation",
                "input": {"action": "validate_pipeline", "item": {"x": 1}},
                "params": {"action": "validate_pipeline"},
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert isinstance(body, dict)
        # A typed result, not an error shrug.
        assert "error" not in body or body.get("error") is None


# ── B5: tenant isolation (smoke; depth in test_two_tenant_isolation) ────────
def test_b5_unauthenticated_execute_is_rejected():
    with TestClient(app) as c:  # no Authorization header
        resp = c.post("/execute", json={"block": "validation", "input": {}})
        assert resp.status_code in (401, 403), resp.text


# ── B6: construction container primary extraction (document -> structured) ──
@pytest.mark.asyncio
async def test_b6_construction_document_extraction(tmp_path):
    from app.containers.construction import ConstructionContainer

    doc = tmp_path / "contract.txt"
    doc.write_text(
        "CONTRACT AGREEMENT\n"
        "The Contractor shall supply and install 1200 m3 of C40 concrete and "
        "85000 kg of reinforcement. The Contract Sum is AED 12,500,000. "
        "Practical Completion within 540 days. Retention shall be 10%.",
        encoding="utf-8",
    )
    container = ConstructionContainer()
    out = await container.route("process_document", {"file_path": str(doc)}, {})
    assert out.get("status") == "success", out
    # The container auto-classifies and routes (drawing / contract / spec / ...);
    # whichever path runs must return a real structured envelope, not a shrug.
    assert out.get("file_name") == "contract.txt"
    classified = out.get("doc_type") or out.get("action") or out.get("contract_type")
    assert classified, f"document was not classified/processed: {out}"
    assert len(out.keys()) > 4, f"extraction envelope too thin: {list(out.keys())}"


# ── B3: ingest -> RAG query -> cited answer (needs pgvector) ────────────────
@pytest.mark.skipif(
    os.getenv("DATABASE_URL") is None,
    reason="DATABASE_URL not set; RAG e2e needs pgvector (provided in CI)",
)
def test_b3_ingest_then_cited_answer():
    """Ingest a fact, then prove the platform can find it and will not invent it.

    WHY THIS IS TWO CALLS RATHER THAN ONE ASSERTION
    The original test ingested the SLA and asserted `"99.95" in ans["answer"]`
    from /knowledge/ask alone. That failed in CI for a reason that had nothing
    to do with retrieval: with no LLM key configured, knowledge.py only serves
    the retrieved chunk verbatim when its score clears a 0.6 confidence
    threshold, and otherwise answers honestly that it has nothing relevant.

    The tempting fix is to lower that threshold until the test passes. That
    would be tuning production doctrine to suit a test -- the threshold is
    what stops a weak match being served as an answer, and it protects every
    real caller.

    So retrieval and synthesis are asserted separately, against the endpoints
    that actually own them:

      /knowledge/search  proves the chunk is findable. It returns content and
                         needs no LLM, so this half is a real assertion in CI.
                         If ingestion or vector search breaks, THIS fails.
      /knowledge/ask     proves the answer is either grounded in that chunk or
                         an honest "I don't know" -- and never something else.

    What the test no longer does is require an answer the platform cannot
    honestly give without a model.
    """
    tenant = f"e2e-{uuid.uuid4().hex[:8]}"
    fact = "The service level agreement guarantees 99.95% monthly uptime."
    with _client() as c:
        ing = c.post(
            "/ingestion/text",
            json={"tenant_id": tenant, "project_name": "e2e", "title": "SLA", "text": fact},
        )
        assert ing.status_code == 200, ing.text
        project_id = ing.json()["project_id"]

        # -- retrieval: the half that must work, with or without a model ----
        found = c.post(
            "/knowledge/search",
            json={"query": "What uptime does the SLA guarantee?",
                  "project_id": project_id, "top_k": 3},
        )
        assert found.status_code == 200, found.text
        search = found.json()

        ask = c.post(
            "/knowledge/ask",
            json={"question": "What uptime does the SLA guarantee?",
                  "project_id": project_id, "top_k": 3},
        )
        assert ask.status_code == 200, ask.text
        ans = ask.json()

    assert search["status"] == "success", search
    hits = search.get("results") or []
    assert hits, f"the ingested SLA was not retrievable at all: {search}"
    assert any("99.95" in str(h.get("content", "")) for h in hits), (
        f"the ingested fact was not among the retrieved chunks: {hits}"
    )

    # -- synthesis: grounded, or honestly absent. Never a third thing -------
    assert ans["status"] == "success"
    assert ans.get("chunks_retrieved", 0) >= 1, (
        "ask() reported no chunks even though search() found the fact"
    )
    answer = ans.get("answer", "")
    grounded = "99.95" in answer
    declined = "don't have any relevant information" in answer
    assert grounded or declined, (
        "the answer neither cites the ingested figure nor declines honestly, "
        f"which is the fabrication case this test exists to catch: {answer!r}"
    )
