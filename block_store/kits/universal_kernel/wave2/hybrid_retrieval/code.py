"""Neutral hybrid retrieval: vector similarity + lexical overlap fused with RRF."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from block_store.kits.universal_kernel.wave2.vector_store import Chunk, VectorStore

RRF_K = 60


@dataclass
class HybridResult:
    """Neutral hybrid retrieval result."""

    score: float
    chunk: Chunk
    source_citation: Dict[str, Any]


class RetrievalError(Exception):
    """Raised when hybrid retrieval cannot be performed."""


def _tokenize(text: str) -> List[str]:
    return [t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if t]


def lexical_rank(query: str, chunks: List[Chunk]) -> List[tuple]:
    """BM25-ish token overlap scoring for chunks."""
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    # Collection frequency for IDF.
    token_doc_freq: Dict[str, int] = {}
    chunk_tokens: List[List[str]] = []
    for chunk in chunks:
        tokens = _tokenize(chunk.text)
        chunk_tokens.append(tokens)
        for token in set(tokens):
            token_doc_freq[token] = token_doc_freq.get(token, 0) + 1

    n = len(chunks)
    scores: List[tuple] = []
    for chunk, tokens in zip(chunks, chunk_tokens):
        token_counts: Dict[str, int] = {}
        for token in tokens:
            token_counts[token] = token_counts.get(token, 0) + 1
        score = 0.0
        for token in query_tokens:
            tf = token_counts.get(token, 0)
            if tf == 0:
                continue
            df = token_doc_freq.get(token, 1)
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            score += idf * ((tf * 2.0) / (tf + 1.5))
        if score > 0:
            scores.append((score, chunk))

    scores.sort(key=lambda x: -x[0])
    return scores


def _rrf_fuse(
    vector_results: List,
    lexical_results: List,
    top_k: int,
) -> List[HybridResult]:
    """Fuse vector and lexical rankings with Reciprocal Rank Fusion."""
    fused: Dict[str, Dict[str, Any]] = {}

    for rank, result in enumerate(vector_results, start=1):
        chunk = result.chunk
        entry = fused.setdefault(chunk.id, {"chunk": chunk, "score": 0.0, "vector": None, "lexical": None})
        entry["score"] += 1.0 / (RRF_K + rank)
        entry["vector"] = result.score

    for rank, (score, chunk) in enumerate(lexical_results, start=1):
        entry = fused.setdefault(chunk.id, {"chunk": chunk, "score": 0.0, "vector": None, "lexical": None})
        entry["score"] += 1.0 / (RRF_K + rank)
        entry["lexical"] = score

    ordered = sorted(fused.values(), key=lambda e: -e["score"])[:top_k]
    out: List[HybridResult] = []
    for entry in ordered:
        chunk: Chunk = entry["chunk"]
        source_citation = {
            "chunk_id": chunk.id,
            "text_snippet": (chunk.text or "")[:200],
            "vector_score": entry["vector"],
            "lexical_score": entry["lexical"],
        }
        if chunk.metadata:
            source_citation["metadata"] = dict(chunk.metadata)
        out.append(
            HybridResult(
                score=round(entry["score"], 6),
                chunk=chunk,
                source_citation=source_citation,
            )
        )
    return out


def hybrid_search(
    store: VectorStore,
    tenant_id: str,
    project_id: str,
    query: str,
    query_vector: List[float],
    top_k: int = 5,
) -> Dict[str, Any]:
    """Run vector + lexical hybrid search and return RRF-fused results."""
    if not query or not query.strip():
        raise RetrievalError("query is required")

    vector_results = store.search(tenant_id, project_id, query_vector, top_k=top_k * 4)
    if vector_results:
        lexical_results = lexical_rank(query, [r.chunk for r in vector_results])
    else:
        lexical_results = []

    if not vector_results and not lexical_results:
        return {"results": [], "honesty": "no_sources"}

    results = _rrf_fuse(vector_results, lexical_results, top_k)
    return {
        "results": results,
        "honesty": "hybrid",
    }
