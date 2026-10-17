"""ChatBlock.process — entry-point coverage against a doubled provider.

Why this file exists
--------------------
``tests/blocks/test_chat.py`` drives ``execute`` and asserts only the
UniversalBlock envelope keys, which ``TypedBlock.execute`` supplies whatever
``process`` returned. The control-delete in ``scripts/certify_block.py`` gutted
``ChatBlock.process`` to ``{"block": ..., "status": "success"}`` and that suite
stayed GREEN.

Nothing here touches the network and no API key is required. The provider
transport is doubled inside ``app.blocks.chat`` (the module holds the only
``httpx`` reference the block uses), and every assertion is on a value
``process`` had to build: the assistant text lifted out of the provider
envelope, the prompt it assembled before sending, the offline template it
renders when the provider is absent or refuses, and the 240-character echo
truncation inside that template.

Fixture note: the provider envelope is constructed in-test (there is no
recorded Moonshot response committed to the Store). The system-prompt test
does use a real artifact on disk — ``app/prompts/construction_expert.txt``.
"""

from __future__ import annotations

import json
import types
from pathlib import Path

import httpx
import pytest

from app.blocks import chat as chat_module
from app.blocks.chat import ChatBlock


PROMPTS_DIR = Path(chat_module.__file__).resolve().parents[1] / "prompts"
REAL_SYSTEM_PROMPT = PROMPTS_DIR / "construction_expert.txt"


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self) -> dict:
        return self._payload


def _double_provider(monkeypatch, responder):
    """Replace the httpx the chat block reaches for. Returns the request log."""
    calls: list[dict] = []

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, headers=None, json=None):
            calls.append({"url": url, "headers": headers or {}, "body": json or {}})
            return responder(json or {})

    monkeypatch.setattr(
        chat_module,
        "httpx",
        types.SimpleNamespace(
            AsyncClient=_FakeAsyncClient,
            TimeoutException=httpx.TimeoutException,
        ),
    )
    return calls


def _completion(content: str, usage: dict | None = None) -> _FakeResponse:
    return _FakeResponse(
        200,
        {
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": usage if usage is not None else {},
        },
    )


@pytest.fixture
def cloud_env(monkeypatch):
    """A configured-but-doubled Kimi: key present, endpoint/model at defaults."""
    monkeypatch.setenv("KIMI_API_KEY", "not-a-real-key")
    for name in ("MOONSHOT_API_KEY", "KIMI_MODEL", "MOONSHOT_MODEL",
                 "KIMI_BASE_URL", "MOONSHOT_BASE_URL"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def offline_env(monkeypatch):
    """No provider key at all — the template responder must carry the answer."""
    for name in ("KIMI_API_KEY", "MOONSHOT_API_KEY",
                 "KIMI_BASE_URL", "MOONSHOT_BASE_URL"):
        monkeypatch.delenv(name, raising=False)


# ── the provider's answer becomes the block's payload ──────────────────────


async def test_provider_content_becomes_the_text_payload(monkeypatch, cloud_env):
    answer = "Slump for C30 to BS EN 206 is class S3 (100-150 mm)."
    calls = _double_provider(
        monkeypatch, lambda body: _completion(answer, {"total_tokens": 137})
    )

    result = await ChatBlock().process(
        {"text": "What slump class applies to C30?"},
        {"max_tokens": 512, "temperature": 0.1},
    )

    assert result["status"] == "success"
    assert result["text"] == answer
    assert result["provider"] == "kimi"
    assert result["model"] == "kimi-k2-0905-preview"
    assert result["tokens"] == {"total_tokens": 137}

    # The request the block resolved from llm_config, not a hard-coded string.
    assert len(calls) == 1
    assert calls[0]["url"] == "https://api.moonshot.ai/v1/chat/completions"
    assert calls[0]["headers"]["Authorization"] == "Bearer not-a-real-key"
    assert calls[0]["body"]["max_tokens"] == 512
    assert calls[0]["body"]["temperature"] == 0.1


async def test_system_prompt_file_on_disk_is_loaded_into_the_conversation(
    monkeypatch, cloud_env
):
    """A real prompt artifact is read and prepended; the echo proves it landed."""
    assert REAL_SYSTEM_PROMPT.is_file()
    first_line = REAL_SYSTEM_PROMPT.read_text(encoding="utf-8").splitlines()[0]

    _double_provider(
        monkeypatch,
        lambda body: _completion(json.dumps(body["messages"])),
    )

    result = await ChatBlock().process(
        {"text": "Summarise the handover procedure."},
        {"system_prompt_file": "construction_expert.txt"},
    )

    echoed = json.loads(result["text"])
    assert [m["role"] for m in echoed] == ["system", "user"]
    assert echoed[0]["content"].startswith(first_line)
    assert "senior Project Management Consultant" in echoed[0]["content"]
    assert echoed[1]["content"] == "Summarise the handover procedure."


async def test_system_prompt_file_outside_the_prompts_dir_is_dropped(
    monkeypatch, cloud_env
):
    """Traversal is refused: the conversation goes out with no system turn."""
    _double_provider(
        monkeypatch,
        lambda body: _completion(json.dumps(body["messages"])),
    )

    result = await ChatBlock().process(
        {"text": "hello"},
        {"system_prompt_file": "../core/llm_config.py"},
    )

    echoed = json.loads(result["text"])
    assert [m["role"] for m in echoed] == ["user"]
    assert "KIMI_BASE_URL" not in result["text"], "prompt file content leaked"


async def test_retrieved_chunks_are_folded_into_the_user_turn(monkeypatch, cloud_env):
    """use_rag rewrites the message; the doubled provider echoes what it got."""
    from app.core.rag import retriever as retriever_module

    chunk = retriever_module.RetrievedChunk(
        doc_id="spec-03",
        chunk_index=7,
        text="Curing shall continue for a minimum of seven days.",
        score=0.82,
        metadata={},
    )

    async def _fake_retrieve(query, project_id, k=5):
        assert query == "How long is curing?"
        assert project_id == "proj-42"
        return [chunk]

    monkeypatch.setattr(retriever_module, "retrieve", _fake_retrieve)
    _double_provider(
        monkeypatch,
        lambda body: _completion(body["messages"][-1]["content"]),
    )

    result = await ChatBlock().process(
        {"text": "How long is curing?"},
        {"use_rag": True, "project_id": "proj-42"},
    )

    sent = result["text"]
    assert sent.startswith("Relevant project context:\n[spec-03#7] ")
    assert "Curing shall continue for a minimum of seven days." in sent
    assert sent.endswith("User question: How long is curing?")


# ── the failure paths produce their own, quotable payloads ─────────────────


async def test_provider_http_error_is_reported_through_the_offline_template(
    monkeypatch, cloud_env
):
    _double_provider(
        monkeypatch,
        lambda body: _FakeResponse(503, text="upstream capacity exceeded"),
    )

    result = await ChatBlock().process({"text": "ping"}, {})

    assert result["status"] == "success", "chat must never go dark"
    assert result["provider"] == "offline_template"
    assert result["model"] == "template:v1"
    assert "HTTP 503" in result["primary_error"]
    assert "upstream capacity exceeded" in result["primary_error"]
    assert "**Chat is running in offline mode.**" in result["text"]
    assert "> ping" in result["text"]


async def test_no_key_names_the_env_var_that_would_restore_chat(offline_env):
    result = await ChatBlock().process({"text": "estimate the rebar tonnage"}, {})

    assert result["status"] == "success"
    assert result["provider"] == "offline_template"
    assert result["primary_error"] == "MOONSHOT_API_KEY not configured"
    assert "Set `KIMI_API_KEY` (or `MOONSHOT_API_KEY`) in `.env`." in result["text"]
    assert "> estimate the rebar tonnage" in result["text"]


async def test_offline_template_truncates_the_echoed_message_at_240_chars(offline_env):
    message = "A" * 500
    result = await ChatBlock().process({"text": message}, {})

    assert result["provider"] == "offline_template"
    assert "> " + "A" * 237 + "...\n" in result["text"]
    assert "A" * 238 not in result["text"], "message echoed past the 240-char cap"


async def test_empty_message_is_echoed_as_the_literal_empty_marker(offline_env):
    result = await ChatBlock().process({"text": "   "}, {})

    assert result["provider"] == "offline_template"
    assert "> (empty)" in result["text"]
