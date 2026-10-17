"""Answer-producing blocks on /v1/execute route through the grounding stage."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.core.grounding import verdict_log_path
from app.routers.execute import ExecuteRequest, _run_block

AUTH = {"id": "key-1", "email": "t@example.com", "tier": "free"}


class _StubBlock:
    def __init__(self, result):
        self._result = result

    async def execute(self, input_data, params):
        return {
            "block": "chat",
            "request_id": "t",
            "status": "success",
            "result": dict(self._result),
            "confidence": 1.0,
            "source_id": "chat-t",
            "metadata": {},
            "processing_time_ms": 0,
        }


def _patches(stub, name="chat"):
    return [
        patch("app.routers.execute.BLOCK_REGISTRY", {name: object}),
        patch("app.routers.execute.get_block_instance", lambda n: stub),
        patch("app.routers.execute.enforce_block_access", lambda n, a: None),
        patch("app.routers.execute.adapt_input", lambda d, b: d),
    ]


async def _run(stub, name, input_data):
    ps = _patches(stub, name)
    for p in ps:
        p.start()
    try:
        return await _run_block(
            ExecuteRequest(block=name, input=input_data, params={}), AUTH
        )
    finally:
        for p in ps:
            p.stop()


@pytest.mark.asyncio
async def test_chat_answer_with_invented_url_is_blocked(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "storage"))
    stub = _StubBlock({"status": "success", "text": "Get it at https://evil.invalid/x.zip"})

    response = await _run(stub, "chat", {"text": "where do I download?"})

    assert response["grounding"]["verdict"] == "blocked"
    assert "evil.invalid" not in json.dumps(response["result"])
    assert response["result"]["text"] is None

    entries = [
        json.loads(l) for l in verdict_log_path().read_text(encoding="utf-8").splitlines()
    ]
    assert entries[-1]["verdict"] == "blocked"
    assert entries[-1]["surface"] == "execute:chat"


@pytest.mark.asyncio
async def test_knowledge_answer_grounded_in_sources_passes(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "storage"))
    stub = _StubBlock(
        {
            "status": "success",
            "answer": "The retention period is 36 months.",
            "sources": [{"text": "Policy: retention period is 36 months."}],
        }
    )

    response = await _run(stub, "knowledge", {"question": "retention period?"})

    assert response["grounding"]["verdict"] == "grounded"
    assert response["result"]["answer"] == "The retention period is 36 months."


@pytest.mark.asyncio
async def test_non_answer_block_is_not_gated(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "storage"))
    stub = _StubBlock({"status": "success", "value": 42})

    response = await _run(stub, "memory", {"action": "get", "key": "k"})
    assert "grounding" not in response
