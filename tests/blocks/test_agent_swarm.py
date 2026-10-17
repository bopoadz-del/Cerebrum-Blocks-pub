"""Tests for Agent Swarm Block."""

import pytest
from app.blocks import AgentSwarmBlock


@pytest.fixture
def swarm_block():
    return AgentSwarmBlock()


@pytest.mark.asyncio
async def test_swarm_block_execute_structure(swarm_block):
    """Test that Agent Swarm block returns standardized JSON structure."""
    result = await swarm_block.execute(
        {
            "project_id": "test-001",
            "objective": "Say hello",
            "agents": [
                {"name": "greeter", "role": "custom", "goal": "Say hello"}
            ],
            "tasks": [
                {"id": "t1", "description": "Say hello world", "agent": "greeter"}
            ],
        },
        {"action": "execute"},
    )

    assert "block" in result
    assert result["block"] == "agent_swarm"
    assert "request_id" in result
    assert "status" in result
    assert "result" in result
    assert "confidence" in result
    assert "metadata" in result
    assert "source_id" in result
    assert "processing_time_ms" in result


@pytest.mark.asyncio
async def test_swarm_block_metadata(swarm_block):
    """Test Agent Swarm block metadata."""
    assert swarm_block.name == "agent_swarm"
    assert swarm_block.config.version == "1.0.0"
    assert swarm_block.config.requires_api_key == False


@pytest.mark.asyncio
async def test_swarm_dependency_resolution(swarm_block):
    """Test topological sort of tasks."""
    tasks = [
        {"id": "a", "description": "Task A", "agent": "ag1", "dependencies": []},
        {"id": "b", "description": "Task B", "agent": "ag1", "dependencies": ["a"]},
        {"id": "c", "description": "Task C", "agent": "ag1", "dependencies": ["a"]},
        {"id": "d", "description": "Task D", "agent": "ag1", "dependencies": ["b", "c"]},
    ]
    waves = swarm_block._resolve_dependencies(tasks)
    assert waves[0] == ["a"]
    assert set(waves[1]) == {"b", "c"}
    assert waves[2] == ["d"]


@pytest.mark.asyncio
async def test_swarm_missing_agents(swarm_block):
    """Test demo mode when agents/tasks are missing."""
    result = await swarm_block.execute(
        {"project_id": "test", "objective": "Do nothing", "agents": [], "tasks": []},
        {"action": "execute"},
    )
    assert result["result"].get("status") == "success"
    assert result["result"].get("mode") == "demo"


@pytest.mark.asyncio
async def test_swarm_unknown_agent(swarm_block):
    """Test validation fails when task references unknown agent."""
    result = await swarm_block.execute(
        {
            "project_id": "test",
            "objective": "Do nothing",
            "agents": [{"name": "alice", "role": "custom", "goal": "test"}],
            "tasks": [{"id": "t1", "description": "Task", "agent": "bob"}],
        },
        {"action": "execute"},
    )
    inner = result.get("result", result)
    assert inner.get("status") == "error"


@pytest.mark.asyncio
async def test_swarm_async_queue(swarm_block):
    """Test async execution returns job ID."""
    result = await swarm_block.execute(
        {
            "project_id": "async-test",
            "objective": "Async test",
            "agents": [{"name": "a1", "role": "custom", "goal": "test"}],
            "tasks": [{"id": "t1", "description": "Quick task", "agent": "a1"}],
        },
        {"action": "execute_async"},
    )
    inner = result.get("result", result)
    assert "job_id" in inner
    assert inner.get("status") in ("queued", "running", "completed")


@pytest.mark.asyncio
async def test_swarm_job_status(swarm_block):
    """Test job status lookup."""
    # Queue a job first
    queued = await swarm_block.execute(
        {
            "project_id": "status-test",
            "objective": "Status test",
            "agents": [{"name": "a1", "role": "custom", "goal": "test"}],
            "tasks": [{"id": "t1", "description": "Task", "agent": "a1"}],
        },
        {"action": "execute_async"},
    )
    job_id = queued.get("result", {}).get("job_id", "")

    status = await swarm_block.execute(job_id, {"action": "status"})
    inner = status.get("result", status)
    assert "status" in inner


@pytest.mark.asyncio
async def test_swarm_health(swarm_block):
    """Test health check endpoint."""
    result = await swarm_block.execute(None, {"action": "health"})
    inner = result.get("result", result)
    assert inner.get("status") in ("healthy", "degraded")
    assert inner.get("block_id") == "agent_swarm"
