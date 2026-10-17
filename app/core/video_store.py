"""Video metadata storage — in-memory (dev default) or TimescaleDB/PostgreSQL.

Set ``DATABASE_URL`` to a PostgreSQL/Timescale connection string to persist
events. Without it, an in-process store is used so tests and local dev work
without external dependencies.

Schema (created on first use when DATABASE_URL is set)::

    CREATE TABLE IF NOT EXISTS video_events (
        id          TEXT PRIMARY KEY,
        camera_id   TEXT NOT NULL,
        source_id   TEXT NOT NULL,
        timestamp   TIMESTAMPTZ NOT NULL,
        payload     JSONB NOT NULL,
        created_at  TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_video_events_camera_ts
        ON video_events (camera_id, timestamp DESC);
"""

from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import List, Optional
from uuid import uuid4

from app.core.connector_events import Anomaly, VideoMetadata

logger = logging.getLogger(__name__)


class VideoStore(ABC):
    @abstractmethod
    async def store(self, metadata: VideoMetadata) -> str:
        """Persist metadata; return event id."""

    @abstractmethod
    async def list_by_camera(
        self, camera_id: str, *, limit: int = 100
    ) -> List[VideoMetadata]:
        ...

    @abstractmethod
    async def list_anomalies(
        self, *, since: Optional[datetime] = None, limit: int = 100
    ) -> List[Anomaly]:
        ...


class InMemoryVideoStore(VideoStore):
    def __init__(self) -> None:
        self._events: List[VideoMetadata] = []

    async def store(self, metadata: VideoMetadata) -> str:
        event_id = str(uuid4())[:12]
        stored = metadata.model_copy(update={"source_id": metadata.source_id or event_id})
        self._events.append(stored)
        return event_id

    async def list_by_camera(
        self, camera_id: str, *, limit: int = 100
    ) -> List[VideoMetadata]:
        matches = [e for e in self._events if e.camera_id == camera_id]
        return list(reversed(matches[-limit:]))

    async def list_anomalies(
        self, *, since: Optional[datetime] = None, limit: int = 100
    ) -> List[Anomaly]:
        found: List[Anomaly] = []
        for event in reversed(self._events):
            for anomaly in event.anomalies:
                if since and anomaly.timestamp < since:
                    continue
                found.append(anomaly)
                if len(found) >= limit:
                    return found
        return found


class PostgresVideoStore(VideoStore):
    """Async PostgreSQL/Timescale backend via asyncpg."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool = None
        self._schema_ready = False

    async def _get_pool(self):
        import asyncio

        current_loop = asyncio.get_running_loop()
        # Defensive: recreate the pool if it was bound to a different event loop
        # (common in tests where each TestClient runs on its own loop).
        if self._pool is not None:
            pool_loop = getattr(self._pool, "_loop", None)
            if pool_loop is not current_loop or pool_loop.is_closed():
                try:
                    await self._pool.close()
                except Exception:
                    pass
                self._pool = None
                self._schema_ready = False

        if self._pool is None:
            import asyncpg

            self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=5)
        if not self._schema_ready:
            await self._ensure_schema()
            self._schema_ready = True
        return self._pool

    async def _ensure_schema(self) -> None:
        pool = self._pool
        if pool is None:
            return
        async with pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS video_events (
                    id          TEXT PRIMARY KEY,
                    camera_id   TEXT NOT NULL,
                    source_id   TEXT NOT NULL,
                    timestamp   TIMESTAMPTZ NOT NULL,
                    payload     JSONB NOT NULL,
                    created_at  TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_video_events_camera_ts
                ON video_events (camera_id, timestamp DESC)
                """
            )

    async def store(self, metadata: VideoMetadata) -> str:
        event_id = str(uuid4())[:12]
        pool = await self._get_pool()
        payload = json.loads(metadata.model_dump_json())
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO video_events (id, camera_id, source_id, timestamp, payload)
                VALUES ($1, $2, $3, $4, $5::jsonb)
                """,
                event_id,
                metadata.camera_id,
                metadata.source_id,
                metadata.timestamp,
                json.dumps(payload),
            )
        return event_id

    async def list_by_camera(
        self, camera_id: str, *, limit: int = 100
    ) -> List[VideoMetadata]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT payload FROM video_events
                WHERE camera_id = $1
                ORDER BY timestamp DESC
                LIMIT $2
                """,
                camera_id,
                limit,
            )
        return [VideoMetadata.model_validate(json.loads(r["payload"])) for r in rows]

    async def list_anomalies(
        self, *, since: Optional[datetime] = None, limit: int = 100
    ) -> List[Anomaly]:
        pool = await self._get_pool()
        since = since or datetime.min.replace(tzinfo=timezone.utc)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT payload FROM video_events
                WHERE timestamp >= $1
                ORDER BY timestamp DESC
                LIMIT $2
                """,
                since,
                limit * 5,
            )
        found: List[Anomaly] = []
        for row in rows:
            meta = VideoMetadata.model_validate(json.loads(row["payload"]))
            for anomaly in meta.anomalies:
                if since and anomaly.timestamp < since:
                    continue
                found.append(anomaly)
                if len(found) >= limit:
                    return found
        return found


_store: Optional[VideoStore] = None


def get_video_store() -> VideoStore:
    global _store
    if _store is not None:
        return _store
    dsn = os.getenv("DATABASE_URL", "").strip()
    if dsn:
        try:
            _store = PostgresVideoStore(dsn)
            logger.info("video_store: using PostgreSQL/Timescale backend")
        except Exception as exc:
            logger.warning("video_store: DATABASE_URL set but init failed (%s) — in-memory", exc)
            _store = InMemoryVideoStore()
    else:
        _store = InMemoryVideoStore()
        logger.debug("video_store: using in-memory backend (set DATABASE_URL for persistence)")
    return _store


def reset_video_store(store: Optional[VideoStore] = None) -> None:
    """Test helper — swap or clear the singleton."""
    global _store
    _store = store
