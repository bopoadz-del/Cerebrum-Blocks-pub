"""Tests for the neutral LLM provider sub-kit."""

import io
import json

import pytest

from block_store.kits.universal_kernel.wave2.llm_provider import (
    KimiProvider,
    LLMConfigurationError,
    OpenAIProvider,
    get_provider,
)
from block_store.kits.universal_kernel.wave2.llm_provider import code as provider_code


def test_stub_provider_returns_coherent_response():
    provider = get_provider("stub")
    completion = provider.complete("Question: What is the capital of France?")
    assert "Stub answer" in completion.text
    assert completion.honesty == "deterministic_stub"
    assert completion.model == "deterministic-stub-v1"
    assert completion.usage["total_tokens"] > 0


def test_stub_provider_includes_usage_metadata():
    provider = get_provider("stub")
    completion = provider.complete("hello world")
    assert "prompt_tokens" in completion.usage
    assert "completion_tokens" in completion.usage
    assert "total_tokens" in completion.usage
    assert "cost_usd" in completion.usage


def test_stub_provider_is_deterministic():
    provider = get_provider("stub")
    c1 = provider.complete("repeat me")
    c2 = provider.complete("repeat me")
    assert c1.text == c2.text


def test_openai_provider_requires_api_key():
    with pytest.raises(LLMConfigurationError):
        OpenAIProvider(api_key=None)


def test_factory_unknown_provider():
    with pytest.raises(LLMConfigurationError):
        get_provider("unknown")


# ── Kimi (Moonshot) provider — the platform's LLM ──────────────────────────


def test_kimi_provider_requires_api_key(monkeypatch):
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    with pytest.raises(LLMConfigurationError):
        KimiProvider(api_key=None)


def test_factory_returns_kimi_provider(monkeypatch):
    monkeypatch.setenv("KIMI_API_KEY", "sk-test-kimi")
    assert isinstance(get_provider("kimi"), KimiProvider)
    assert isinstance(get_provider("moonshot"), KimiProvider)


def test_kimi_provider_completes_over_openai_compatible_api(monkeypatch):
    monkeypatch.setenv("KIMI_API_KEY", "sk-test-kimi")

    captured = {}

    class _FakeResp:
        def __init__(self, payload):
            self._payload = payload

        def read(self):
            return json.dumps(self._payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def _fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResp(
            {
                "choices": [{"message": {"content": "The SLA guarantees 99.95% uptime."}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 9, "total_tokens": 21},
            }
        )

    monkeypatch.setattr(provider_code.urllib.request, "urlopen", _fake_urlopen)

    provider = KimiProvider(api_key="sk-test-kimi")
    completion = provider.complete("What uptime does the SLA guarantee?", max_tokens=64)

    assert completion.text == "The SLA guarantees 99.95% uptime."
    assert completion.honesty == "live"
    assert completion.usage["total_tokens"] == 21
    # Correct OpenAI-compatible call shape.
    assert captured["url"].endswith("/chat/completions")
    assert captured["auth"] == "Bearer sk-test-kimi"
    assert captured["body"]["model"] == "kimi-k2-0905-preview"
    assert captured["body"]["messages"][0]["role"] == "user"


def test_kimi_provider_network_failure_fails_closed(monkeypatch):
    import urllib.error

    monkeypatch.setenv("KIMI_API_KEY", "sk-test-kimi")

    def _boom(request, timeout=0):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(provider_code.urllib.request, "urlopen", _boom)
    provider = KimiProvider(api_key="sk-test-kimi")
    with pytest.raises(LLMConfigurationError):
        provider.complete("hello")
