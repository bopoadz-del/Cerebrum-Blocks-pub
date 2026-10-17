"""Recall, measured separately from honesty.

From a live post-mortem: a grounded platform refused to answer about a clause it
could quote verbatim. The content was indexed. It was reachable one turn in six, and
the other five produced a well-formed, correctly-hedged refusal — so every miss
scored as GOOD BEHAVIOUR.

  "The better your anti-hallucination discipline, the more effectively it conceals
   your recall problem."

Nothing in a refusal says whether the answer was absent or merely unreached. So this
file is the instrument that tells those apart:

  * a PROBE SET whose answers are confirmed present in the corpus. There, a refusal
    is a FAILURE, never a pass.
  * each probe asked N times, scored on the count of DISTINCT answers. A one-in-six
    defect is invisible to a single run; it reads as "works, occasionally odd".
  * the instrument itself tested first — one fix was reported as having no effect
    because the measuring script's own regex held a stray control byte, and the
    product had been right all along. A null result deserves the same scepticism as
    a surprising positive.

These run against a fake store rather than a live corpus, because the properties
being asserted are the pipeline's, not any document's: that the threshold does not
narrow the pipe, that the candidate pool scales with the corpus, and that the
operator's verbatim words are always one of the queries.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from app.core import vector_store
from app.core.rag import retriever

# ── a corpus shaped like the one that broke: few documents, very many chunks ──

BIG_DOCS = 9
CHUNKS_PER_DOC = 300

#: The clause the post-mortem's platform could quote but not reach. It sits deep in
#: one big document, with hundreds of near neighbours competing for the same slots.
NEEDLE_DOC = "doc-3"
NEEDLE_INDEX = 211
NEEDLE_TEXT = (
    "Compaction shall be to 95% of maximum dry density determined in accordance with "
    "the referenced method, tested at every 500 m2 of each layer."
)


#: Where the needle sits in the similarity ranking of the whole corpus. Chosen so the
#: probe measures the thing that actually broke: it is OUT of reach of a fixed
#: 20-candidate pool and IN reach of a pool derived from the corpus shape. A needle
#: placed anywhere else measures the instrument instead of the pipeline — the first
#: version of this file put it past rank 1600 and reported 0/6 against a pipeline
#: that was behaving correctly, which is the post-mortem's own "verify the instrument
#: before believing a null result".
NEEDLE_RANK = 150


def _corpus() -> List[Dict[str, Any]]:
    """Nine very large documents, and one clause that is relevant but not nearest.

    Scores descend with rank so the ordering is unambiguous; the needle is spliced in
    at NEEDLE_RANK. Plenty of its own document's neighbouring chunks outrank it, which
    is exactly why a shallow pool never sees it.
    """
    plain: List[Dict[str, Any]] = []
    for doc in range(BIG_DOCS):
        for index in range(CHUNKS_PER_DOC):
            doc_id = f"doc-{doc}"
            if doc_id == NEEDLE_DOC and index == NEEDLE_INDEX:
                continue
            plain.append({
                "chunk_id": f"{doc_id}:{index}",
                "document_id": doc_id,
                "content": f"{doc_id} clause {index} concerning earthworks and layers.",
                "metadata": {"chunk_index": index},
            })

    needle = {
        "chunk_id": f"{NEEDLE_DOC}:{NEEDLE_INDEX}",
        "document_id": NEEDLE_DOC,
        "content": NEEDLE_TEXT,
        "metadata": {"chunk_index": NEEDLE_INDEX},
    }
    ordered = plain[:NEEDLE_RANK] + [needle] + plain[NEEDLE_RANK:]
    for rank, row in enumerate(ordered):
        # Strictly descending, so "rank" and "score order" are the same thing and the
        # fake cannot disagree with itself.
        row["score"] = 0.99 - rank * 0.0001
    return ordered


@pytest.fixture
def fake_store(monkeypatch):
    """A store that honours top_k and threshold the way the real SQL now does:
    filter first, then limit. The point of the fake is to make the ORDER of those
    two operations visible, because getting it backwards is the defect."""
    calls: List[Dict[str, Any]] = []
    rows = _corpus()

    async def search_vectors(project_id, query_text, top_k=5, threshold=0.3):
        calls.append({"query": query_text, "top_k": top_k, "threshold": threshold})
        kept = [r for r in rows if r["score"] >= threshold]
        kept.sort(key=lambda r: -r["score"])
        return [dict(r) for r in kept[:top_k]]

    monkeypatch.setattr(vector_store, "search_vectors", search_vectors)
    monkeypatch.setattr(retriever.vector_store, "search_vectors", search_vectors)
    return calls


# ── the instrument is tested before it is believed ────────────────────────

def test_the_probe_corpus_really_contains_the_needle():
    """Verify the instrument first. A probe set that does not contain its own answer
    reports every run as a failure and teaches nothing."""
    rows = _corpus()
    needles = [r for r in rows
               if r["document_id"] == NEEDLE_DOC
               and r["metadata"]["chunk_index"] == NEEDLE_INDEX]
    assert len(needles) == 1, "exactly one needle, or the count below is meaningless"
    assert needles[0]["content"] == NEEDLE_TEXT
    assert len(rows) == BIG_DOCS * CHUNKS_PER_DOC


def test_the_needle_is_not_simply_the_top_hit():
    """If the needle were the nearest neighbour the probe would pass on any pipeline
    and prove nothing about recall."""
    rows = sorted(_corpus(), key=lambda r: -r["score"])
    top = rows[0]
    assert not (top["document_id"] == NEEDLE_DOC
                and top["metadata"]["chunk_index"] == NEEDLE_INDEX)


def test_the_needle_sits_where_the_probe_can_actually_measure_something():
    """The instrument's own calibration. The needle must be beyond a fixed shallow
    pool and within a derived one, or the probe reports on itself.

    This assertion is the reason the first version of this file was wrong: it placed
    the needle past rank 1600 and then reported 0/6 against a pipeline that was
    behaving correctly.
    """
    rows = sorted(_corpus(), key=lambda r: -r["score"])
    rank = next(i for i, r in enumerate(rows)
                if r["document_id"] == NEEDLE_DOC
                and r["metadata"]["chunk_index"] == NEEDLE_INDEX)

    shallow = vector_store.CANDIDATE_POOL_FLOOR
    derived = vector_store.candidate_pool_size(5, CHUNKS_PER_DOC)
    assert rank >= shallow, (
        f"needle at rank {rank} is inside the old fixed pool of {shallow}; the probe "
        f"would pass even with the defect present")
    assert rank < derived, (
        f"needle at rank {rank} is outside the derived pool of {derived}; the probe "
        f"would fail even with the defect fixed")


# ── the pipe must not narrow ──────────────────────────────────────────────

def test_raising_the_threshold_must_not_shrink_the_result_set(fake_store):
    """The defect this replaced: the threshold was applied in Python AFTER the SQL
    LIMIT, so asking for 5 above a high bar returned however many of the nearest 5
    happened to clear it — sometimes none — while chunks that cleared it sat
    unfetched at rank 6."""
    async def go(threshold):
        return await vector_store.search_vectors(
            "p1", "compaction", top_k=5, threshold=threshold)

    lenient = asyncio.run(go(0.0))
    strict = asyncio.run(go(0.9))
    assert len(lenient) == 5
    assert len(strict) == 5, (
        "a stricter threshold returned fewer results — the filter is being applied "
        "after the limit, which is a narrowing pipe, not a quality bar")
    assert all(c["score"] >= 0.9 for c in strict)


def test_the_real_sql_filters_before_it_limits():
    """Asserted on the query text, because the ordering is the whole property and a
    fake store cannot prove what the database was asked."""
    import inspect

    source = inspect.getsource(vector_store.search_vectors)
    where = source.index("WHERE score >= $4")
    limit = source.index("LIMIT $3")
    assert where < limit, "the threshold must be applied before the limit"
    assert "ORDER BY distance" in source


# ── the candidate pool is the recall ceiling ──────────────────────────────

def test_the_candidate_pool_scales_with_how_chunky_the_corpus_really_is():
    """A reranker cannot promote what the first stage never fetched, so this number
    IS the recall ceiling. A fixed multiple held while documents were small and broke
    silently when they became 300-chunk specifications."""
    small = vector_store.candidate_pool_size(5, chunks_per_doc_p95=4)
    large = vector_store.candidate_pool_size(5, chunks_per_doc_p95=CHUNKS_PER_DOC)
    assert large > small, (
        "the pool did not grow with the corpus — this is the 'diversity heuristic "
        "tuned to document count, not document size' defect")
    assert large >= CHUNKS_PER_DOC // 2, (
        f"a pool of {large} over documents of {CHUNKS_PER_DOC} chunks still only "
        f"sees one document's worth of near neighbours")


def test_the_pool_never_collapses_below_its_floor():
    assert vector_store.candidate_pool_size(1, chunks_per_doc_p95=1) >= 20
    assert vector_store.candidate_pool_size(1, chunks_per_doc_p95=None) >= 20
    assert vector_store.candidate_pool_size(1, chunks_per_doc_p95=0) >= 20


def test_an_unmeasured_corpus_is_not_treated_as_a_small_one():
    """corpus_shape reports measured=False with no pool. A caller that reads the
    zeroes as "a tiny corpus" would choose the smallest pool for the largest
    unknown."""
    shape = asyncio.run(vector_store.corpus_shape("p1"))
    assert shape["measured"] is False
    assert shape["chunks_per_doc_p95"] == 0
    # And the derived pool from that zero is the generous fallback, not a tiny one.
    assert vector_store.candidate_pool_size(5, shape["chunks_per_doc_p95"]) >= 20


# ── a model is never the sole author of the query ─────────────────────────

def test_the_operator_words_are_always_one_of_the_queries(fake_store):
    """The one link in the path no model touches."""
    asyncio.run(retriever.retrieve_for(
        "what is the compaction requirement",
        "p1", k=5,
        model_queries=["earthworks layer density testing frequency"]))

    queries = [c["query"] for c in fake_store]
    assert "what is the compaction requirement" in queries, (
        "the operator's verbatim words were not retrieved on — the system is then as "
        "non-deterministic as the model that wrote the query")
    assert len(queries) == 2


def test_retrieval_still_happens_when_the_model_writes_nothing(fake_store):
    chunks = asyncio.run(retriever.retrieve_for(
        "what is the compaction requirement", "p1", k=5))
    assert chunks
    assert [c["query"] for c in fake_store] == ["what is the compaction requirement"]


def test_a_model_query_identical_to_the_operators_is_not_run_twice(fake_store):
    """It would add nothing and would double a chunk's apparent support."""
    asyncio.run(retriever.retrieve_for(
        "compaction", "p1", k=3, model_queries=["compaction"]))
    assert len(fake_store) == 1


def test_every_chunk_records_which_leg_found_it(fake_store):
    chunks = asyncio.run(retriever.retrieve_for(
        "compaction", "p1", k=5, model_queries=["density"]))
    assert chunks
    assert all(c.found_by for c in chunks)
    # Both legs hit the same fake rows, so agreement is recorded rather than one leg
    # silently overwriting the other.
    assert any(len(c.found_by) > 1 for c in chunks)


def test_the_recall_report_says_which_leg_carried_it(fake_store):
    chunks = asyncio.run(retriever.retrieve_for(
        "compaction", "p1", k=5, model_queries=["density"]))
    report = retriever.recall_report(chunks)
    assert report["chunks"] == len(chunks)
    assert report["operator_leg_contributed"] is True
    assert (report["operator_only"] + report["model_only"]
            + report["found_by_both"]) <= report["chunks"]


# ── the probe set: a refusal here is a failure ────────────────────────────

def test_the_needle_is_reached_on_every_run_not_one_in_six(fake_store):
    """THE instrument. The answer is confirmed present, so a miss is a failure — and
    it is asked repeatedly, because a one-in-six defect passes a single run.

    The pipeline under test is deterministic given the query, so six identical runs
    must give six identical answers. That is the point: the moment a model composes
    the query, this test is the thing that notices.
    """
    async def one_run():
        chunks = await retriever.retrieve_for(
            "compaction requirement", "p1",
            k=vector_store.candidate_pool_size(5, CHUNKS_PER_DOC))
        return [(c.doc_id, c.chunk_index) for c in chunks]

    runs = [asyncio.run(one_run()) for _ in range(6)]

    distinct = {tuple(r) for r in runs}
    assert len(distinct) == 1, (
        f"{len(distinct)} distinct answers across 6 identical runs — a disagreement "
        f"between identical runs is usually two code paths, not flakiness")

    reached = [(NEEDLE_DOC, NEEDLE_INDEX) in run for run in runs]
    assert all(reached), (
        f"the needle is IN the corpus and was reached {sum(reached)}/6 times. A "
        f"refusal on this probe is a failure, never a pass — that is what separates "
        f"recall from honesty")


def test_the_old_fixed_pool_would_have_missed_it_every_time(fake_store):
    """The before, measured rather than asserted from memory.

    With the pool that WAS there — a flat floor of 20 — the needle is unreachable on
    all six runs, and the platform would have produced six well-formed refusals about
    a clause it holds. This is the control that gives the test above its meaning: a
    probe that passes both before and after is measuring nothing.
    """
    async def one_run(k):
        chunks = await retriever.retrieve_for("compaction requirement", "p1", k=k)
        return [(c.doc_id, c.chunk_index) for c in chunks]

    before = [asyncio.run(one_run(vector_store.CANDIDATE_POOL_FLOOR)) for _ in range(6)]
    after = [asyncio.run(one_run(
        vector_store.candidate_pool_size(5, CHUNKS_PER_DOC))) for _ in range(6)]

    hit_before = sum((NEEDLE_DOC, NEEDLE_INDEX) in run for run in before)
    hit_after = sum((NEEDLE_DOC, NEEDLE_INDEX) in run for run in after)

    assert hit_before == 0, (
        f"the control reached it {hit_before}/6 with the shallow pool, so this probe "
        f"cannot show the fix mattered")
    assert hit_after == 6, f"reached {hit_after}/6 with the derived pool"
