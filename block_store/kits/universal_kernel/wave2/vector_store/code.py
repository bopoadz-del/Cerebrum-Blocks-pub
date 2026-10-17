"""Neutral vector store: in-memory backend and optional pgvector adapter stub."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np


@dataclass
class Chunk:
    """Neutral chunk record."""

    id: str
    text: str
    vector: List[float]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchResult:
    """Neutral search result."""

    score: float
    chunk: Chunk


class VectorStoreError(Exception):
    """Raised when a vector store operation fails."""


class VectorStore:
    """In-memory vector store scoped by tenant and project."""

    def __init__(self) -> None:
        self._chunks: Dict[str, List[Chunk]] = {}  # key: "tenant_id:project_id"

    def _key(self, tenant_id: str, project_id: str) -> str:
        return f"{tenant_id}:{project_id}"

    def upsert(
        self,
        tenant_id: str,
        project_id: str,
        chunks: List[Chunk],
    ) -> int:
        if not tenant_id or not project_id:
            raise VectorStoreError("tenant_id and project_id are required")
        key = self._key(tenant_id, project_id)
        stored = self._chunks.get(key, [])
        # Replace chunks with the same id; keep others.
        existing_ids = {c.id for c in stored}
        new_ids = {c.id for c in chunks}
        kept = [c for c in stored if c.id not in new_ids]
        kept.extend(chunks)
        self._chunks[key] = kept
        return len(chunks)

    def search(
        self,
        tenant_id: str,
        project_id: str,
        query_vector: List[float],
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        if not tenant_id or not project_id:
            raise VectorStoreError("tenant_id and project_id are required")
        key = self._key(tenant_id, project_id)
        candidates = self._chunks.get(key, [])
        if not candidates:
            return []

        q = np.asarray(query_vector, dtype=np.float32)
        if q.ndim != 1:
            raise VectorStoreError("query_vector must be 1-D")

        scored: List[SearchResult] = []
        for chunk in candidates:
            if filters:
                meta = chunk.metadata or {}
                if not all(meta.get(k) == v for k, v in filters.items()):
                    continue
            vec = np.asarray(chunk.vector, dtype=np.float32)
            if vec.shape[0] != q.shape[0]:
                raise VectorStoreError(
                    f"chunk vector dimension {vec.shape[0]} does not match query {q.shape[0]}"
                )
            norm_q = np.linalg.norm(q)
            norm_v = np.linalg.norm(vec)
            if norm_q == 0 or norm_v == 0:
                score = 0.0
            else:
                score = float(np.dot(q, vec) / (norm_q * norm_v))
            scored.append(SearchResult(score=score, chunk=chunk))

        scored.sort(key=lambda r: -r.score)
        return scored[:top_k]

    def count(self, tenant_id: str, project_id: str) -> int:
        return len(self._chunks.get(self._key(tenant_id, project_id), []))

    def clear(self, tenant_id: str, project_id: str) -> None:
        self._chunks.pop(self._key(tenant_id, project_id), None)


class PgvectorStore(VectorStore):
    """Optional pgvector adapter stub; requires DATABASE_URL to initialize."""

    def __init__(self, connection_string: Optional[str] = None) -> None:
        super().__init__()
        self.connection_string = connection_string or os.getenv("DATABASE_URL")
        if not self.connection_string:
            raise VectorStoreError("DATABASE_URL is required for PgvectorStore")
