"""Neutral embedding provider: deterministic feature-hash fallback + optional OpenAI."""

from __future__ import annotations

import hashlib
import math
import os
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import numpy as np

EMBEDDING_DIMENSION = 384
_FEATURE_HASH_MODEL = "feature-hash-v1"
_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+(?:['\-][a-zA-Z0-9]+)*", re.UNICODE)


class EmbeddingConfigurationError(Exception):
    """Raised when a configured provider cannot be initialized."""


class EmbeddingProvider(ABC):
    """Abstract embedding provider."""

    dimensions: int = EMBEDDING_DIMENSION
    model_name: str = "unknown"

    @abstractmethod
    def embed(self, texts: List[str]) -> Dict[str, Any]:
        raise NotImplementedError


def _tokenize(text: str) -> List[str]:
    return _TOKEN_RE.findall((text or "").lower())


def _hash_embedding(text: str, dim: int = EMBEDDING_DIMENSION) -> List[float]:
    """Deterministic signed feature-hash embedding."""
    vector = [0.0] * dim
    for token in _tokenize(text):
        token_bytes = token.encode("utf-8")
        digest = hashlib.sha256(token_bytes).digest()
        idx = int.from_bytes(digest[:4], "big") % dim
        sign = 1 if digest[4] % 2 == 0 else -1
        weight = 1.0 + math.log1p(len(token))
        vector[idx] += sign * weight
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        # Empty/whitespace input: return a deterministic unit vector.
        vector[0] = 1.0
        return vector
    return [v / norm for v in vector]


def normalize(vectors: List[List[float]]) -> List[List[float]]:
    """L2-normalize a list of vectors; zero vectors stay zero."""
    arr = np.asarray(vectors, dtype=np.float32)
    if arr.ndim != 2:
        raise ValueError("vectors must be a 2-D list")
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return (arr / norms).astype(np.float32).tolist()


class HashEmbeddingProvider(EmbeddingProvider):
    """Deterministic feature-hash fallback; no external model or API key."""

    model_name = _FEATURE_HASH_MODEL
    dimensions = EMBEDDING_DIMENSION

    def embed(self, texts: List[str]) -> Dict[str, Any]:
        if texts is None:
            raise ValueError("texts must not be None")
        vectors = [_hash_embedding(text) for text in texts]
        return {
            "vectors": vectors,
            "honesty": "deterministic_hash_fallback",
            "model": self.model_name,
            "dimensions": self.dimensions,
        }


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI embedding provider; fails closed when OPENAI_API_KEY is missing."""

    model_name = "text-embedding-3-small"
    dimensions = EMBEDDING_DIMENSION

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise EmbeddingConfigurationError("OPENAI_API_KEY is required")

    def embed(self, texts: List[str]) -> Dict[str, Any]:
        # Neutral stub: real implementation would call the OpenAI API.
        raise NotImplementedError("OpenAI embedding call is not implemented in this neutral kit")


def get_provider(
    provider_id: str = "hash",
    api_key: Optional[str] = None,
) -> EmbeddingProvider:
    """Factory for the configured embedding provider."""
    if provider_id == "hash":
        return HashEmbeddingProvider()
    if provider_id == "openai":
        return OpenAIEmbeddingProvider(api_key=api_key)
    raise EmbeddingConfigurationError(f"unknown provider_id: {provider_id!r}")
