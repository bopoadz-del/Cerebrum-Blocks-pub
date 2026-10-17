"""RAG retriever backed by the pgvector vector store.

A model must never be the SOLE author of a retrieval query.

The ranker is deterministic given a query string. That sentence is true of the
ranker and false of the system, and believing the first form cost a sibling platform
a measurement round: the query string was written by the answer model at temperature
1, so one operator question became a different search on every run, and a clause that
was in the corpus the whole time was reached 1 turn in 6. The other five turns
produced a well-formed, correctly-hedged refusal — and every miss scored as good
behaviour.

So ``retrieve_for`` takes the operator's VERBATIM words as well, retrieves on both,
and merges. The operator's text is the one link in the path no model touches, and
every returned chunk records which query found it, so a recall problem cannot hide
behind a plausible refusal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

from app.core import vector_store

#: Chunks to ask for per query leg. The merge returns at most ``k`` overall, but each
#: leg must be allowed to fill it alone — the operator's phrasing and the model's may
#: land nowhere near each other, and halving each leg would make the merge weaker
#: than either query on its own.
LEG_OVERSAMPLE = 1


@dataclass
class RetrievedChunk:
    doc_id: str
    chunk_index: int
    text: str
    score: float
    metadata: dict
    #: Which query leg(s) found this chunk. "operator" is the one no model wrote.
    found_by: list[str] = field(default_factory=list)


def _to_chunk(row: dict, idx: int, leg: str) -> RetrievedChunk:
    metadata = row.get("metadata", {}) or {}
    return RetrievedChunk(
        doc_id=str(row.get("document_id", "")),
        chunk_index=int(metadata.get("chunk_index", idx)),
        text=row.get("content", ""),
        score=float(row.get("score", 0.0)),
        metadata=metadata,
        found_by=[leg],
    )


async def retrieve(query: str, project_id: str, k: int = 5) -> list[RetrievedChunk]:
    """Retrieve the top ``k`` chunks for ``query`` from ``project_id``.

    Single-query retrieval, kept for callers that genuinely have one query — a
    keyword lookup, a probe, a test. When the query came from a MODEL, use
    ``retrieve_for`` and pass the operator's words too.
    """
    results = await vector_store.search_vectors(
        project_id, query, top_k=k,
        threshold=vector_store.DEFAULT_SIMILARITY_THRESHOLD,
    )
    return [_to_chunk(row, idx, "query") for idx, row in enumerate(results)]


async def retrieve_for(
    operator_text: str,
    project_id: str,
    k: int = 5,
    model_queries: Sequence[str] = (),
) -> list[RetrievedChunk]:
    """Retrieve on the operator's verbatim words AND any model-composed queries.

    The operator leg always runs, even when a model wrote something cleverer. That
    leg is the only part of the path a model does not touch, so it is the only part
    that answers the same way twice.

    Every chunk records which legs found it. A chunk found ONLY by a model query is
    exactly as usable as any other — but the record is what lets a probe set show
    that the operator leg was carrying the recall, or that it was not.
    """
    operator_text = (operator_text or "").strip()
    legs: list[tuple[str, str]] = []
    if operator_text:
        legs.append(("operator", operator_text))
    for index, query in enumerate(model_queries or ()):
        query = (query or "").strip()
        # A model query identical to the operator's adds nothing and would double a
        # chunk's apparent support.
        if query and query != operator_text:
            legs.append((f"model[{index}]", query))

    if not legs:
        return []

    merged: dict[tuple[str, int], RetrievedChunk] = {}
    for leg, query in legs:
        rows = await vector_store.search_vectors(
            project_id, query, top_k=k * LEG_OVERSAMPLE,
            threshold=vector_store.DEFAULT_SIMILARITY_THRESHOLD,
        )
        for idx, row in enumerate(rows):
            chunk = _to_chunk(row, idx, leg)
            key = (chunk.doc_id, chunk.chunk_index)
            existing = merged.get(key)
            if existing is None:
                merged[key] = chunk
                continue
            # Same chunk from two legs: keep the better score and record BOTH legs.
            # Agreement between an operator query and a model query is the strongest
            # signal available here, and discarding one leg would hide it.
            if chunk.score > existing.score:
                existing.score = chunk.score
            if leg not in existing.found_by:
                existing.found_by.append(leg)

    ranked = sorted(merged.values(), key=lambda c: (-c.score, c.doc_id, c.chunk_index))
    return ranked[:k]


def recall_report(chunks: Iterable[RetrievedChunk]) -> dict:
    """Which leg actually carried the recall.

    Reported so a probe set can tell a careful system from a silent one: if the
    operator leg found nothing the model leg did not, the merge is costing a query
    for nothing; if the model leg is the only one landing, the system is as
    non-deterministic as the model that wrote the query.
    """
    chunks = list(chunks)
    operator_only = [c for c in chunks if c.found_by == ["operator"]]
    model_only = [c for c in chunks if c.found_by and "operator" not in c.found_by]
    both = [c for c in chunks if "operator" in c.found_by and len(c.found_by) > 1]
    return {
        "chunks": len(chunks),
        "operator_only": len(operator_only),
        "model_only": len(model_only),
        "found_by_both": len(both),
        "operator_leg_contributed": bool(operator_only or both),
    }
