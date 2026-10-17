"""Tests for the neutral embedding provider sub-kit."""

import pytest

from block_store.kits.universal_kernel.wave2.embedding_provider import (
    EMBEDDING_DIMENSION,
    EmbeddingConfigurationError,
    HashEmbeddingProvider,
    OpenAIEmbeddingProvider,
    get_provider,
    normalize,
)


def test_hash_provider_returns_384_dimensions():
    provider = HashEmbeddingProvider()
    result = provider.embed(["hello world", "another sentence"])
    assert result["honesty"] == "deterministic_hash_fallback"
    assert result["model"] == "feature-hash-v1"
    assert len(result["vectors"]) == 2
    assert len(result["vectors"][0]) == EMBEDDING_DIMENSION


def test_hash_provider_is_deterministic():
    provider = HashEmbeddingProvider()
    v1 = provider.embed(["repeatable"])["vectors"][0]
    v2 = provider.embed(["repeatable"])["vectors"][0]
    assert v1 == v2


def test_hash_provider_normalizes_vectors():
    provider = HashEmbeddingProvider()
    vectors = provider.embed(["hello"])["vectors"]
    norm = sum(x * x for x in vectors[0]) ** 0.5
    assert pytest.approx(norm, 0.001) == 1.0


def test_normalize_helper():
    vectors = [[3.0, 4.0], [0.0, 0.0]]
    normalized = normalize(vectors)
    assert pytest.approx(normalized[0][0], 0.001) == 0.6
    assert normalized[1] == [0.0, 0.0]


def test_openai_provider_requires_api_key():
    with pytest.raises(EmbeddingConfigurationError):
        OpenAIEmbeddingProvider(api_key=None)


def test_factory_unknown_provider():
    with pytest.raises(EmbeddingConfigurationError):
        get_provider("unknown")


def test_factory_openai_without_key():
    with pytest.raises(EmbeddingConfigurationError):
        get_provider("openai")
