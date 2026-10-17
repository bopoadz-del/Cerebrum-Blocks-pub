"""Payload tests for posture_model.

A control-delete gut of process() returns a plausible success and cannot
produce a refusal, a failed sampler, or the text sample_posture returned.
The serve config on disk is the real fixture.
"""

from pathlib import Path

import pytest

from app.blocks.posture_model import PostureModelBlock
from app.vendor.cerebrum_slm.posture_model import (
    CHECKPOINT_URI,
    ContextMissing,
    PostureSampleError,
    load_serve_config,
    sample_posture,
)

SERVE_CONFIG = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "vendor"
    / "cerebrum_slm"
    / "configs"
    / "serve"
    / "posture-epoch2.json"
)

CONTEXT = {"chunks": [{"id": "c1", "text": "attached by the fork"}]}


def test_serve_config_on_disk_pins_the_checkpoint():
    loaded = load_serve_config()
    assert SERVE_CONFIG.is_file()
    assert loaded["checkpoint"] == CHECKPOINT_URI
    assert loaded["source_sha"] == "4e167a7"
    assert "retrieval_core" not in SERVE_CONFIG.read_text(encoding="utf-8")


def test_sample_posture_refuses_before_any_post_when_context_is_missing():
    def explode(*_args, **_kwargs):
        raise AssertionError("sampler was called without fork_context")

    with pytest.raises(ContextMissing):
        sample_posture("what is the cover?", fork_context=None, post=explode)
    with pytest.raises(ContextMissing):
        sample_posture("what is the cover?", post=explode)


def test_sample_posture_posts_the_pinned_checkpoint(monkeypatch):
    monkeypatch.setenv("TINKER_API_KEY", "test-key-not-a-secret")
    seen = {}

    def post(url, payload, api_key):
        seen["url"] = url
        seen["payload"] = payload
        seen["api_key"] = api_key
        return {"choices": [{"text": "sampled-answer"}]}

    result = sample_posture(
        "what is the cover?",
        fork_context=CONTEXT,
        allowed_formula_ids=["formula-7"],
        post=post,
    )

    assert result["text"] == "sampled-answer"
    assert result["checkpoint"] == CHECKPOINT_URI
    assert seen["payload"]["model"] == CHECKPOINT_URI
    assert seen["api_key"] == "test-key-not-a-secret"
    assert seen["url"].endswith("/completions")
    prompt = seen["payload"]["prompt"]
    assert "formula-7" in prompt
    assert "attached by the fork" in prompt
    assert "retrieval_core" not in prompt


def test_sample_posture_fails_closed_without_an_api_key(monkeypatch):
    monkeypatch.delenv("TINKER_API_KEY", raising=False)

    def explode(*_args, **_kwargs):
        raise AssertionError("sampler was called without TINKER_API_KEY")

    with pytest.raises(PostureSampleError, match="TINKER_API_KEY"):
        sample_posture("what is the cover?", fork_context=CONTEXT, post=explode)


async def test_process_refuses_when_fork_context_is_missing_or_none(monkeypatch):
    def explode(*_args, **_kwargs):
        raise AssertionError("sample_posture called without context")

    monkeypatch.setattr("app.blocks.posture_model.sample_posture", explode)
    block = PostureModelBlock()

    missing = await block.process({"user_text": "what is the cover?"})
    assert missing["status"] == "refused"
    assert missing["answer"] is None
    assert "not attached" in missing["error"]

    explicit = await block.process(
        {"user_text": "what is the cover?", "fork_context": None}
    )
    assert explicit["status"] == "refused"
    assert explicit["answer"] is None


async def test_process_returns_the_sample_when_context_is_attached(monkeypatch):
    captured = {}

    def fake(user_text, fork_context=None, allowed_formula_ids=None):
        captured["user_text"] = user_text
        captured["fork_context"] = fork_context
        captured["allowed_formula_ids"] = allowed_formula_ids
        return {"text": "SAMPLED-TOKEN", "checkpoint": CHECKPOINT_URI}

    monkeypatch.setattr("app.blocks.posture_model.sample_posture", fake)
    block = PostureModelBlock()
    result = await block.process(
        {
            "user_text": "what is the cover?",
            "fork_context": CONTEXT,
            "allowed_formula_ids": ["formula-7"],
        }
    )

    assert result["status"] == "ok"
    assert result["answer"] == "SAMPLED-TOKEN"
    assert result["checkpoint"] == CHECKPOINT_URI
    assert captured == {
        "user_text": "what is the cover?",
        "fork_context": CONTEXT,
        "allowed_formula_ids": ["formula-7"],
    }


async def test_process_forwards_context_from_params_and_fails_without_a_key(monkeypatch):
    monkeypatch.delenv("TINKER_API_KEY", raising=False)
    block = PostureModelBlock()
    result = await block.process(
        "what is the cover?",
        params={"fork_context": CONTEXT},
    )
    assert result["status"] == "failed"
    assert result["answer"] is None
    assert "TINKER_API_KEY" in result["error"]


def test_block_source_does_not_embed_a_retriever():
    root = Path(__file__).resolve().parents[2]
    paths = [
        root / "app" / "blocks" / "posture_model.py",
        root / "app" / "vendor" / "cerebrum_slm" / "posture_model" / "client.py",
        root / "block_registry" / "posture_model" / "block.py",
    ]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "retrieval_core" not in text
        assert "import retriev" not in text
