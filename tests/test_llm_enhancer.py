"""Tests for the LLM enhancer block (Kimi / Moonshot).

The block was rewired from the Anthropic SDK to Kimi's OpenAI-compatible HTTP
API (platform is Kimi-only). These tests never hit the real API — they mock
``httpx.AsyncClient`` so the JSON parsing / filtering logic is still exercised.

- ``is_active()`` is False when no Kimi key is set.
- ``enhance_*`` short-circuit to ``{"additions": [], "skipped": True, ...}``
  when no key can be found.
- With a mocked Kimi HTTP response returning JSON additions,
  ``enhance_quantities`` parses them; bad JSON surfaces as an error, not a raise.
- ``process()`` dispatches on ``params.action`` and errors on unknown.
"""

from __future__ import annotations

from typing import Any, Dict, List

import httpx
import pytest

from app.blocks.llm_enhancer import LLMEnhancerBlock


# ── helpers: fake Kimi (OpenAI-compatible) HTTP client ─────────────────────


class _FakeResp:
    def __init__(self, content_text: str) -> None:
        self._content_text = content_text

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Dict[str, Any]:
        return {"choices": [{"message": {"content": self._content_text}}]}


class _FakeAsyncClient:
    """Async-context-manager stand-in for httpx.AsyncClient that captures the
    posted payload and returns a fixed OpenAI-shaped response."""

    captured: List[Dict[str, Any]] = []

    def __init__(self, content_text: str) -> None:
        self._content_text = content_text

    def __call__(self, *args: Any, **kwargs: Any) -> "_FakeAsyncClient":
        return self

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def post(self, url: str, headers: Dict[str, Any], json: Dict[str, Any]) -> _FakeResp:
        _FakeAsyncClient.captured.append(json)
        return _FakeResp(self._content_text)


def _mock_kimi(monkeypatch: pytest.MonkeyPatch, content_text: str) -> None:
    monkeypatch.setenv("KIMI_API_KEY", "sk-test-kimi")
    _FakeAsyncClient.captured = []
    fake = _FakeAsyncClient(content_text)
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: fake)


def _no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)


# ── is_active() ────────────────────────────────────────────────────────────


def test_is_active_false_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_key(monkeypatch)
    assert LLMEnhancerBlock().is_active() is False


def test_is_active_true_with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KIMI_API_KEY", "sk-test-kimi")
    assert LLMEnhancerBlock().is_active() is True


# ── enhance_* short-circuit when no key ────────────────────────────────────


@pytest.mark.asyncio
async def test_enhance_quantities_skipped_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_key(monkeypatch)
    out = await LLMEnhancerBlock().enhance_quantities("some text", {})
    assert out == {"additions": [], "skipped": True, "reason": "client_unavailable"}


@pytest.mark.asyncio
async def test_enhance_risks_skipped_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_key(monkeypatch)
    out = await LLMEnhancerBlock().enhance_risks("some text", [])
    assert out == {"additions": [], "skipped": True, "reason": "client_unavailable"}


@pytest.mark.asyncio
async def test_enhance_rfis_skipped_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_key(monkeypatch)
    out = await LLMEnhancerBlock().enhance_rfis("some text", [])
    assert out == {"additions": [], "skipped": True, "reason": "client_unavailable"}


# ── happy path with a mocked Kimi response ─────────────────────────────────


@pytest.mark.asyncio
async def test_enhance_quantities_parses_additions(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = (
        '{"additions": ['
        '{"item": "switchgear_400v", "quantity": 6, "unit": "ea", '
        '"category": "electrical", "source_quote": "400V switchgear: 6 ea"}'
        "]}"
    )
    _mock_kimi(monkeypatch, payload)
    out = await LLMEnhancerBlock().enhance_quantities(
        "Document text mentioning 400V switchgear: 6 ea",
        {"floor_area_m2": {"quantity": 1000, "unit": "m2"}},
    )
    assert out.get("additions"), "expected at least one parsed addition"
    assert out["additions"][0]["item"] == "switchgear_400v"
    assert out["additions"][0]["quantity"] == 6

    # Verify the Kimi (OpenAI) call shape: system + user messages, token cap,
    # BASELINE + DOCUMENT TEXT in the user content.
    assert len(_FakeAsyncClient.captured) == 1
    body = _FakeAsyncClient.captured[0]
    assert body["max_tokens"] == 4000
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["system", "user"]
    user_content = body["messages"][1]["content"]
    assert "BASELINE:" in user_content
    assert "DOCUMENT TEXT:" in user_content


@pytest.mark.asyncio
async def test_enhance_quantities_handles_bad_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_kimi(monkeypatch, "this is not JSON at all, just prose")
    out = await LLMEnhancerBlock().enhance_quantities("some doc text", {})
    assert out["additions"] == []
    assert "error" in out
    assert "json_parse_failed" in out["error"]


@pytest.mark.asyncio
async def test_enhance_rfis_filters_short_questions(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = (
        '{"additions": ['
        '{"category": "clarification", "subject": "Beam size", '
        '"question": "What is the steel grade for the W14x90 beams on level 3?", '
        '"discipline": "Structural", "severity": "medium", '
        '"source_quote": "W14x90 beams TBD"},'
        '{"category": "clarification", "subject": "TBD", '
        '"question": "TBD", "discipline": "Architecture", '
        '"severity": "low", "source_quote": "TBD"}'
        "]}"
    )
    _mock_kimi(monkeypatch, payload)
    out = await LLMEnhancerBlock().enhance_rfis("text mentioning W14x90 beams TBD", [])
    assert len(out["additions"]) == 1
    assert "steel grade" in out["additions"][0]["question"]


# ── process() dispatch ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_status_reports_inactive(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_key(monkeypatch)
    out = await LLMEnhancerBlock().process({}, {"action": "status"})
    assert out["status"] == "success"
    assert out["is_active"] is False
    assert out["model"]


@pytest.mark.asyncio
async def test_process_status_reports_active(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KIMI_API_KEY", "sk-test-kimi")
    out = await LLMEnhancerBlock().process({}, {"action": "status"})
    assert out["status"] == "success"
    assert out["is_active"] is True


@pytest.mark.asyncio
async def test_process_dispatches_enhance_quantities(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_kimi(
        monkeypatch,
        '{"additions": [{"item": "rebar_20mm", "quantity": 1500, '
        '"unit": "kg", "category": "concrete", "source_quote": "20mm rebar: 1500 kg"}]}',
    )
    out = await LLMEnhancerBlock().process(
        {"text": "doc...", "baseline": {}}, {"action": "enhance_quantities"}
    )
    assert out["status"] == "success"
    assert out["additions"][0]["item"] == "rebar_20mm"


@pytest.mark.asyncio
async def test_process_dispatches_enhance_risks(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_kimi(monkeypatch, '{"additions": []}')
    out = await LLMEnhancerBlock().process(
        {"text": "doc...", "baseline": []}, {"action": "enhance_risks"}
    )
    assert out["status"] == "success"
    assert out["additions"] == []


@pytest.mark.asyncio
async def test_process_dispatches_enhance_rfis(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_kimi(monkeypatch, '{"additions": []}')
    out = await LLMEnhancerBlock().process(
        {"text": "doc...", "baseline": []}, {"action": "enhance_rfis"}
    )
    assert out["status"] == "success"
    assert out["additions"] == []


@pytest.mark.asyncio
async def test_process_unknown_action_errors() -> None:
    out = await LLMEnhancerBlock().process({}, {"action": "do_something_undefined"})
    assert out["status"] == "error"
    assert "Unknown action" in out["error"]
