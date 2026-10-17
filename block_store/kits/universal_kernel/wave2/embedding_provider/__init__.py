"""Embedding provider sub-kit: deterministic feature-hash fallback + optional OpenAI."""

from .code import (
    EMBEDDING_DIMENSION,
    EmbeddingConfigurationError,
    EmbeddingProvider,
    HashEmbeddingProvider,
    OpenAIEmbeddingProvider,
    get_provider,
    normalize,
)

__all__ = [
    "EMBEDDING_DIMENSION",
    "EmbeddingConfigurationError",
    "EmbeddingProvider",
    "HashEmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "get_provider",
    "normalize",
]
