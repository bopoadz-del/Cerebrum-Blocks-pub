"""Tests for aviation_chat_server block."""

import pytest

from app.blocks.aviation_chat_server import AviationChatServerBlock


class _FakeMemory:
    def __init__(self):
        self.store = {}

    async def process(self, input_data, params=None):
        action = input_data.get("action")
        key = input_data.get("key")
        if action == "get":
            return {"value": self.store.get(key), "hit": key in self.store}
        if action == "set":
            self.store[key] = input_data.get("value")
            return {"stored": True, "key": key}
        return {}


class _FakeOrchestrator:
    def __init__(self, result):
        self.result = result

    async def process(self, input_data, params=None):
        return self.result


@pytest.fixture
def chat_block():
    return AviationChatServerBlock()


@pytest.mark.asyncio
async def test_chat_server_requires_session_id(chat_block):
    result = await chat_block.process({"message": "hello"})
    assert result["status"] == "error"
    assert any(f["type"] == "error" for f in result["frames"])


@pytest.mark.asyncio
async def test_chat_server_requires_auth_when_configured(chat_block):
    result = await chat_block.process({
        "session_id": "s1",
        "message": "hello",
    })
    assert result["status"] == "error"
    assert result["frames"][0].get("status_code") == 401


@pytest.mark.asyncio
async def test_chat_server_routes_through_orchestrator_and_streams(chat_block):
    memory = _FakeMemory()
    orchestrator = _FakeOrchestrator({
        "final_output": {
            "verdict": "pass",
            "allowed_response": "The fare is $2,500.",
        }
    })
    chat_block.wire("memory", memory)
    chat_block.wire("orchestrator", orchestrator)

    result = await chat_block.process({
        "session_id": "s1",
        "message": "What is the business class fare?",
        "auth_token": "valid",
        "project_id": "proj_aviation_1",
    })

    assert result["status"] == "success"
    assert result["session_id"] == "s1"
    assert result["memory_stored"] is True
    assert any(f["type"] == "delta" for f in result["frames"])
    assert any(f["type"] == "done" for f in result["frames"])
    # Conversation should contain user + assistant turns.
    assert result["conversation_length"] == 2


@pytest.mark.asyncio
async def test_chat_server_surfaces_orchestrator_failure(chat_block):
    orchestrator = _FakeOrchestrator({
        "final_output": {
            "verdict": "block",
            "blocked_reason": "Fare figure not found in retrieved chunks.",
        }
    })
    chat_block.wire("memory", _FakeMemory())
    chat_block.wire("orchestrator", orchestrator)

    result = await chat_block.process({
        "session_id": "s2",
        "message": "What is the fare?",
        "auth_token": "valid",
    })

    assert result["status"] == "success"
    error_frames = [f for f in result["frames"] if f["type"] == "error"]
    assert len(error_frames) >= 1


@pytest.mark.asyncio
async def test_chat_server_induced_failure_is_visible(chat_block):
    class _FailingOrchestrator:
        async def process(self, input_data, params=None):
            raise RuntimeError("orchestrator timeout")

    chat_block.wire("memory", _FakeMemory())
    chat_block.wire("orchestrator", _FailingOrchestrator())

    result = await chat_block.process({
        "session_id": "s3",
        "message": "hello",
        "auth_token": "valid",
    })

    assert result["status"] == "error"
    assert "orchestrator timeout" in result["error"]
    assert any(f["type"] == "error" for f in result["frames"])
