"""pgvector-backed vector store foundation.

This module is designed to fail-soft: if ``DATABASE_URL`` is unset or Postgres
is unreachable, all public functions return empty lists / ``None`` and log a
warning so the rest of the application can still boot and serve traffic.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
from typing import Any

try:
    import asyncpg
    from asyncpg import Pool

    DRIVER_AVAILABLE = True
except ImportError:  # the driver is optional; see the module docstring
    # The docstring above promises this module fails SOFT so the rest of the
    # application can still boot -- and a hard `import asyncpg` broke that promise at
    # this line, before any of the fail-soft branches could run. Every file that
    # imports this one was uncollectable without the driver, including the retrieval
    # recall probes, which is the instrument that would notice.
    asyncpg = None  # type: ignore[assignment]
    Pool = Any  # type: ignore[assignment,misc]
    DRIVER_AVAILABLE = False

logger = logging.getLogger(__name__)

_pool: Pool | None = None
_embedding_model: Any | None = None

VECTOR_DIMENSION = int(os.getenv("VECTOR_DIMENSION", "384"))


def get_database_url() -> str | None:
    """Read ``DATABASE_URL`` from the environment."""
    return os.getenv("DATABASE_URL")


async def _register_vector_codec(conn: asyncpg.Connection) -> None:
    """Register a text codec for the pgvector ``vector`` type.

    asyncpg does not ship with native vector support, so we pass vectors as
    bracketed float lists (``[...]``) in text format.
    """
    await conn.set_type_codec(
        "vector",
        encoder=lambda v: "[" + ",".join(str(x) for x in v) + "]",
        decoder=lambda s: [float(x) for x in s.strip("[]").split(",") if x],
        schema="public",
        format="text",
    )


async def init_pool() -> Pool | None:
    """Create the asyncpg connection pool with a small retry loop.

    Returns the existing pool if already initialized. Returns ``None`` when
    ``DATABASE_URL`` is missing or Postgres cannot be reached.
    """
    global _pool
    if _pool is not None:
        return _pool

    dsn = get_database_url()
    if not dsn:
        # Intentional configuration, not a fault: the store service runs
        # without RAG demo flows and never sets DATABASE_URL.
        logger.info(
            "DATABASE_URL not set — vector store disabled; expected when "
            "running without the RAG demo flows"
        )
        return None

    last_exc: Exception | None = None
    for attempt in range(1, 4):
        try:
            # Ensure the extension exists before registering the vector codec;
            # asyncpg cannot set a type codec for a type that is not yet present
            # in the target database.
            setup_conn = await asyncpg.connect(dsn)
            try:
                await setup_conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            finally:
                await setup_conn.close()

            _pool = await asyncpg.create_pool(
                dsn,
                min_size=2,
                max_size=10,
                init=_register_vector_codec,
            )
            logger.info("Vector store Postgres pool initialized")
            return _pool
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "Failed to initialize vector store pool (attempt %s/3): %s",
                attempt,
                exc,
            )
            await asyncio.sleep(1)

    logger.error(
        "Could not initialize vector store Postgres pool after 3 attempts: %s",
        last_exc,
    )
    _pool = None
    return None


async def close_pool() -> None:
    """Close the asyncpg pool if it was opened."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Vector store Postgres pool closed")


def embeddings_offline() -> bool:
    """Deterministic no-download mode (CI / airgapped deployments).

    When CEREBRUM_EMBEDDINGS_OFFLINE=1 every embedding site must skip
    model downloads and use its deterministic fallback. The universal
    kernel test suite explicitly expects the hash fallback to be
    surfaced with the honesty label, so this mode is a documented
    contract, not a silent degradation.
    """
    return os.getenv("CEREBRUM_EMBEDDINGS_OFFLINE", "") == "1"


def get_embedding_model() -> Any | None:
    """Lazy-load the sentence-transformers embedding model."""
    global _embedding_model
    if _embedding_model is not None:
        return _embedding_model

    model_name = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    if embeddings_offline():
        logger.info(
            "CEREBRUM_EMBEDDINGS_OFFLINE=1: skipping model download; "
            "callers use the deterministic hash fallback"
        )
        return None
    try:
        from sentence_transformers import SentenceTransformer

        _embedding_model = SentenceTransformer(model_name)
        logger.info("Loaded embedding model: %s", model_name)
        return _embedding_model
    except Exception as exc:
        logger.warning("Could not load embedding model %s: %s", model_name, exc)
        return None


def _json_meta(value: Any) -> dict:
    """Decode a json/jsonb value from asyncpg (str) into a dict."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value) if isinstance(value, str) else dict(value)
    except Exception as exc:  # noqa: BLE001 — logged, not swallowed
        # This used to return {} in silence, and the metadata it drops carries
        # `chunk_index`. The retriever then falls back to the enumeration index, so a
        # chunk whose metadata failed to parse is reported under a DIFFERENT chunk
        # number as fact. Say which chunk and why, or the citation is wrong and
        # nothing shows it.
        logger.warning(
            "chunk metadata did not decode (%s: %s); the chunk keeps its content but "
            "loses chunk_index, so any citation of it will carry a substituted index",
            type(exc).__name__, exc)
        return {}


def _hash_embedding(text: str, dim: int = VECTOR_DIMENSION) -> list[float]:
    """Deterministic, normalized fallback embedding based on SHA-256."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    vec: list[float] = []
    for i in range(dim):
        byte = digest[i % len(digest)]
        # Map byte to [-1, 1]
        value = (byte / 127.5) - 1.0
        vec.append(value)
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


def embed_text(text: str) -> list[float]:
    """Return an embedding vector for ``text``.

    Uses the configured sentence-transformers model when available; otherwise
    falls back to a deterministic hash-based vector of length
    ``VECTOR_DIMENSION``.
    """
    if not isinstance(text, str):
        text = str(text)

    model = get_embedding_model()
    if model is not None:
        try:
            import numpy as np

            vector = model.encode(text, convert_to_numpy=True)
            if isinstance(vector, np.ndarray):
                vector = vector.tolist()
            return [float(x) for x in vector]
        except Exception as exc:
            logger.warning("Embedding model failed for text: %s", exc)

    return _hash_embedding(text)


def _pool_unavailable() -> bool:
    if not DRIVER_AVAILABLE:
        # Said once per call rather than swallowed: "no results" because the driver
        # is absent is a different fact from "no results" because nothing matched,
        # and a caller that cannot tell them apart will report an empty corpus.
        logger.warning(
            "Vector store driver (asyncpg) is not installed; returning empty result. "
            "This is NOT an empty corpus")
        return True
    if _pool is None:
        logger.warning("Vector store pool is not initialized; returning empty result")
        return True
    return False


async def ensure_project(
    tenant_id: str,
    project_id: str | None = None,
    name: str = "default",
) -> dict | None:
    """Insert a project for ``(tenant_id, name)`` if absent and return it."""
    if _pool_unavailable():
        return None

    async with _pool.acquire() as conn:
        if project_id:
            row = await conn.fetchrow(
                """
                INSERT INTO projects (id, tenant_id, name)
                VALUES ($1, $2, $3)
                ON CONFLICT (tenant_id, name) DO UPDATE SET name = EXCLUDED.name
                RETURNING id, tenant_id, name, created_at
                """,
                project_id,
                tenant_id,
                name,
            )
        else:
            row = await conn.fetchrow(
                """
                INSERT INTO projects (tenant_id, name)
                VALUES ($1, $2)
                ON CONFLICT (tenant_id, name) DO UPDATE SET name = EXCLUDED.name
                RETURNING id, tenant_id, name, created_at
                """,
                tenant_id,
                name,
            )
        return dict(row) if row else None


async def create_document(
    project_id: str,
    title: str,
    source_path: str,
    doc_metadata: dict,
) -> dict | None:
    """Insert a document and return its row."""
    if _pool_unavailable():
        return None

    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO documents (project_id, title, source_path, doc_metadata)
            VALUES ($1, $2, $3, $4::jsonb)
            RETURNING id, project_id, title, source_path, doc_metadata, created_at
            """,
            project_id,
            title,
            source_path,
            json.dumps(doc_metadata or {}),
        )
        if not row:
            return None
        result = dict(row)
        result["doc_metadata"] = _json_meta(result.get("doc_metadata"))
        return result


async def create_ingestion_job(document_id: str) -> dict | None:
    """Create a pending ingestion job for ``document_id``."""
    if _pool_unavailable():
        return None

    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO ingestion_jobs (document_id, status)
            VALUES ($1, 'pending')
            RETURNING id, document_id, status, stage, error_message, started_at, finished_at, chunk_count
            """,
            document_id,
        )
        return dict(row) if row else None


async def get_ingestion_job(job_id: str) -> dict | None:
    """Return a single ingestion job row by ``job_id``."""
    if _pool_unavailable():
        return None

    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, document_id, status, stage, error_message, started_at, finished_at, chunk_count
            FROM ingestion_jobs
            WHERE id = $1
            """,
            job_id,
        )
        return dict(row) if row else None


async def update_job_status(
    job_id: str,
    status: str,
    stage: str | None = None,
    error_message: str | None = None,
    chunk_count: int | None = None,
) -> dict | None:
    """Update an ingestion job, setting ``finished_at`` on terminal statuses."""
    if _pool_unavailable():
        return None

    sets = ["status = $1"]
    params: list[Any] = [status]

    if stage is not None:
        sets.append(f"stage = ${len(params) + 1}")
        params.append(stage)
    if error_message is not None:
        sets.append(f"error_message = ${len(params) + 1}")
        params.append(error_message)
    if chunk_count is not None:
        sets.append(f"chunk_count = ${len(params) + 1}")
        params.append(chunk_count)

    if status == "processing":
        sets.append("started_at = COALESCE(started_at, NOW())")
    if status in ("completed", "failed"):
        sets.append("finished_at = NOW()")

    params.append(job_id)
    query = f"""
        UPDATE ingestion_jobs
        SET {', '.join(sets)}
        WHERE id = ${len(params)}
        RETURNING id, document_id, status, stage, error_message, started_at, finished_at, chunk_count
    """

    async with _pool.acquire() as conn:
        row = await conn.fetchrow(query, *params)
        return dict(row) if row else None


async def add_chunks(document_id: str, chunks: list[dict]) -> int:
    """Embed and insert ``chunks`` for ``document_id``.

    Each chunk dict must contain ``content`` and may contain ``metadata``.
    Returns the number of rows inserted.
    """
    if _pool_unavailable():
        return 0
    if not chunks:
        return 0

    try:
        async with _pool.acquire() as conn:
            doc_row = await conn.fetchrow(
                "SELECT project_id FROM documents WHERE id = $1",
                document_id,
            )
            if doc_row is None:
                logger.warning("Document %s not found; no chunks inserted", document_id)
                return 0

            project_id = doc_row["project_id"]
            records = []
            for idx, chunk in enumerate(chunks):
                content = chunk.get("content", "")
                metadata = chunk.get("metadata") or chunk.get("chunk_metadata") or {}
                embedding = embed_text(content)
                records.append(
                    (
                        document_id,
                        project_id,
                        content,
                        embedding,
                        idx,
                        json.dumps(metadata),
                    )
                )

            await conn.executemany(
                """
                INSERT INTO chunks (document_id, project_id, content, embedding, chunk_index, chunk_metadata)
                VALUES ($1, $2, $3, $4::vector, $5, $6::jsonb)
                """,
                records,
            )
            return len(records)
    except Exception as exc:
        logger.exception("Failed to add chunks for document %s: %s", document_id, exc)
        return 0


#: One similarity threshold, in one place. It was 0.5 here, 0.3 in
#: ``hybrid_search`` and 0.3 hard-coded again in ``rag/retriever.py`` — three
#: numbers for one concept, and the odd one out was the default nobody passed, so a
#: caller that forgot the argument silently got a stricter cut than every caller
#: that remembered.
DEFAULT_SIMILARITY_THRESHOLD = 0.3


async def search_vectors(
    project_id: str,
    query_text: str,
    top_k: int = 5,
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> list[dict]:
    """Search chunks by cosine similarity.

    Returns up to ``top_k`` results with ``score >= threshold``. Each result
    contains ``chunk_id``, ``document_id``, ``content``, ``score``, and
    ``metadata``.

    THE THRESHOLD IS APPLIED IN SQL, BEFORE THE LIMIT. It used to be applied in
    Python afterwards, which made raising the threshold SHRINK the result set
    instead of reaching deeper: a caller asking for 5 above 0.5 got however many of
    the nearest 5 happened to clear the bar — sometimes none — while chunks that
    cleared it sat unfetched at rank 6. A narrowing pipe of exactly the kind that
    turns a present clause into an honest-looking refusal.
    """
    if _pool_unavailable():
        return []

    embedding = embed_text(query_text)
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, document_id, content, chunk_metadata, score
            FROM (
                SELECT id, document_id, content, chunk_metadata,
                       1 - (embedding <=> $1::vector) AS score,
                       embedding <=> $1::vector AS distance
                FROM chunks
                WHERE project_id = $2
            ) scored
            WHERE score >= $4
            ORDER BY distance
            LIMIT $3
            """,
            embedding,
            project_id,
            top_k,
            float(threshold),
        )

    return [
        {
            "chunk_id": str(row["id"]),
            "document_id": str(row["document_id"]),
            "content": row["content"],
            "score": float(row["score"]),
            "metadata": _json_meta(row["chunk_metadata"]),
        }
        for row in rows
    ]


#: The candidate pool a reranker sees, as a multiple of the answers wanted. The
#: reranker can only promote what the first stage fetched, so this multiple IS the
#: recall ceiling — and it was a bare ``max(top_k * 4, 20)``.
#:
#: A fixed multiple is the defect that made a present clause reachable 1 turn in 6 on
#: a sibling platform. It held while the corpus was many small files. It broke
#: silently when the corpus became nine very large specification PDFs: with hundreds
#: of chunks per document, twenty candidates by pure vector distance are all
#: neighbours from the same few pages, and the asked-for clause loses before the
#: keyword stage is ever consulted.
#:
#: So the pool is derived from how chunky the corpus ACTUALLY is, not assumed. Pass
#: ``chunks_per_doc_p95`` from ``corpus_shape()``; the fallback is deliberately
#: generous rather than tuned for a demo.
CANDIDATE_POOL_MULTIPLE = 4
CANDIDATE_POOL_FLOOR = 20
FALLBACK_CHUNKS_PER_DOC_P95 = 10


def candidate_pool_size(top_k: int, chunks_per_doc_p95: int | None = None) -> int:
    """How many candidates a reranker must see to have a chance of finding it.

    Scaled by the p95 chunks-per-document of the real corpus: a corpus whose typical
    document is 300 chunks needs a far deeper pool than one whose documents are 3,
    for the same ``top_k``, because the near neighbours of any query are drawn from a
    single document's worth of pages.
    """
    p95 = int(chunks_per_doc_p95 or FALLBACK_CHUNKS_PER_DOC_P95)
    p95 = max(p95, 1)
    scaled = top_k * CANDIDATE_POOL_MULTIPLE * max(p95 // FALLBACK_CHUNKS_PER_DOC_P95, 1)
    return max(scaled, CANDIDATE_POOL_FLOOR)


async def corpus_shape(project_id: str) -> dict:
    """What this corpus actually looks like: documents, chunks, and the p95
    chunks-per-document that ``candidate_pool_size`` needs.

    Measured rather than assumed, because the assumption is what broke. Returns
    zeroes when there is no pool, and a caller that gets zeroes must use the
    fallback rather than treating an unmeasured corpus as a small one.
    """
    if _pool_unavailable():
        return {"documents": 0, "chunks": 0, "chunks_per_doc_p95": 0, "measured": False}
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT count(*) AS documents,
                   coalesce(sum(n), 0) AS chunks,
                   coalesce(
                       percentile_disc(0.95) WITHIN GROUP (ORDER BY n), 0
                   ) AS p95
            FROM (
                SELECT document_id, count(*) AS n
                FROM chunks
                WHERE project_id = $1
                GROUP BY document_id
            ) per_doc
            """,
            project_id,
        )
    return {
        "documents": int(row["documents"]),
        "chunks": int(row["chunks"]),
        "chunks_per_doc_p95": int(row["p95"]),
        "measured": True,
    }


async def hybrid_search(
    project_id: str,
    query_text: str,
    top_k: int = 5,
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    chunks_per_doc_p95: int | None = None,
) -> list[dict]:
    """Combine vector similarity with a simple keyword overlap score.

    Vector and keyword scores are normalized to [0, 1] and combined as
    ``0.7 * vector_score + 0.3 * keyword_score``.

    The candidate pool is derived from the corpus shape — see
    ``candidate_pool_size``. A reranker cannot promote what the first stage never
    fetched, so that number is the recall ceiling and it is not a constant.
    """
    candidates = await search_vectors(
        project_id, query_text,
        top_k=candidate_pool_size(top_k, chunks_per_doc_p95),
        threshold=0.0,
    )
    if not candidates:
        return []

    query_tokens = [t for t in query_text.lower().split() if t]

    vector_scores = [c["score"] for c in candidates]
    max_vector = max(vector_scores)
    min_vector = min(vector_scores)

    def normalize_vector_score(score: float) -> float:
        if max_vector == min_vector:
            return 1.0 if max_vector > 0 else 0.0
        return (score - min_vector) / (max_vector - min_vector)

    def keyword_score(content: str) -> float:
        if not query_tokens:
            return 0.0
        content_lower = content.lower()
        matches = sum(1 for token in query_tokens if token in content_lower)
        return matches / len(query_tokens)

    ranked: list[dict] = []
    for candidate in candidates:
        vector_norm = normalize_vector_score(candidate["score"])
        keyword = keyword_score(candidate["content"])
        combined = 0.7 * vector_norm + 0.3 * keyword
        if combined >= threshold:
            candidate["metadata"] = {
                **candidate.get("metadata", {}),
                "vector_score": candidate["score"],
                "keyword_score": keyword,
            }
            candidate["score"] = combined
            ranked.append(candidate)

    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked[:top_k]
