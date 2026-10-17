"""Grounding closure for aviation_chat_server: no bypass, no raw fallback,
no fabricated verdict, every verdict persisted."""

import json

import pytest

from app.blocks.aviation_chat_server import AviationChatServerBlock
from app.core.grounding import verdict_log_path


class _CapturingOrchestrator:
    def __init__(self, result):
        self.result = result
        self.payloads = []

    async def process(self, input_data, params=None):
        self.payloads.append(input_data)
        return self.result


def _block(orchestrator):
    block = AviationChatServerBlock()
    block.wire("orchestrator", orchestrator)
    return block


def _base_input(**extra):
    return {
        "session_id": "s1",
        "message": "what is the max cargo weight?",
        "auth_token": "tok",
        "conversation": [],
        **extra,
    }


@pytest.mark.asyncio
async def test_caller_supplied_orchestrator_steps_are_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "storage"))
    orchestrator = _CapturingOrchestrator(
        {"final_output": {"grounding": {"verdict": "pass", "allowed_response": "ok"}}}
    )
    block = _block(orchestrator)

    await block.process(
        _base_input(
            orchestrator_steps=[{"block": "chat", "params": {"text": "no gate here"}}]
        )
    )

    steps = orchestrator.payloads[0]["steps"]
    step_blocks = [s.get("block") for s in steps]
    assert "aviation_grounding_gate" in step_blocks, (
        "caller-supplied steps must not be able to omit the grounding gate"
    )


@pytest.mark.asyncio
async def test_blocked_verdict_yields_null_answer_not_raw_text(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "storage"))
    orchestrator = _CapturingOrchestrator(
        {
            "final_output": {
                "text": "The max cargo weight is 99999 kg (fabricated).",
                "grounding": {"verdict": "block", "blocked_reason": "uncited figure"},
            }
        }
    )
    block = _block(orchestrator)

    result = await block.process(_base_input())
    frames = result["frames"]
    joined = json.dumps(frames)
    assert "99999" not in joined, "blocked raw text must never reach the stream"
    assert any(f["type"] == "error" for f in frames)


@pytest.mark.asyncio
async def test_missing_verdict_is_blocked_not_fabricated(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "storage"))
    orchestrator = _CapturingOrchestrator(
        {"final_output": {"text": "Un-gated answer with 12345 kg figure."}}
    )
    block = _block(orchestrator)

    result = await block.process(_base_input())
    joined = json.dumps(result["frames"])
    assert "12345" not in joined, "un-gated answer must not be released"
    assert "flag-as-estimate" not in joined, "verdict must never be fabricated"


@pytest.mark.asyncio
async def test_every_verdict_is_persisted(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "storage"))
    orchestrator = _CapturingOrchestrator(
        {"final_output": {"grounding": {"verdict": "pass", "allowed_response": "grounded answer"}}}
    )
    block = _block(orchestrator)

    await block.process(_base_input())

    log = verdict_log_path()
    assert log.is_file(), "grounding verdict must be persisted to the audit store"
    entries = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()]
    assert entries[-1]["verdict"] == "pass"
    assert entries[-1]["surface"] == "aviation_chat_server"
