"""Vector store sub-kit: in-memory backend and optional pgvector adapter stub."""

from .code import Chunk, PgvectorStore, SearchResult, VectorStore, VectorStoreError

__all__ = ["Chunk", "PgvectorStore", "SearchResult", "VectorStore", "VectorStoreError"]
