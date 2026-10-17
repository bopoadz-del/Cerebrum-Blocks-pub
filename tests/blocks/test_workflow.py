"""Tests for Workflow Block."""

import pytest
from app.blocks import WorkflowBlock


@pytest.fixture
def workflow_block():
    return WorkflowBlock()


@pytest.mark.asyncio
async def test_workflow_block_execute_structure(workflow_block):
    """Test standardized JSON structure."""
    result = await workflow_block.execute(
        {
            "pipeline_id": "test-pipe",
            "steps": [
                {"id": "s1", "block": "chat", "input": {"text": "hello"}, "params": {}}
            ],
        },
        {"action": "run"},
    )
    assert "block" in result
    assert result["block"] == "workflow"
    assert "request_id" in result
    assert "status" in result
    assert "result" in result
    assert "confidence" in result
    assert "metadata" in result
    assert "source_id" in result
    assert "processing_time_ms" in result


@pytest.mark.asyncio
async def test_workflow_block_metadata(workflow_block):
    assert workflow_block.name == "workflow"
    assert workflow_block.config.version == "1.0.0"
    assert workflow_block.config.requires_api_key == False


@pytest.mark.asyncio
async def test_workflow_empty_steps(workflow_block):
    result = await workflow_block.execute(
        {"pipeline_id": "empty", "steps": []},
        {"action": "run"},
    )
    inner = result.get("result", result)
    assert inner.get("status") == "error"


@pytest.mark.asyncio
async def test_workflow_variable_interpolation(workflow_block):
    context = {
        "pipeline_id": "test",
        "steps": {
            "step1": {"result": {"text": "Hello World"}}
        },
    }
    step_input = {"text": "{{steps.step1.result.text}}"}
    interpolated = workflow_block._interpolate(step_input, context)
    assert interpolated["text"] == "Hello World"


@pytest.mark.asyncio
async def test_workflow_list_and_get(workflow_block):
    # Register a pipeline
    await workflow_block.execute(
        {"pipeline_id": "demo", "steps": [{"id": "s1", "block": "chat", "input": {}}]},
        {"action": "run"},
    )
    list_result = await workflow_block.execute(None, {"action": "list"})
    assert list_result["result"]["status"] == "success"

    get_result = await workflow_block.execute("demo", {"action": "get"})
    assert get_result["result"]["status"] == "success"


@pytest.mark.asyncio
async def test_workflow_history(workflow_block):
    result = await workflow_block.execute(None, {"action": "history"})
    assert result["result"]["status"] == "success"
    assert "runs" in result["result"]


@pytest.mark.asyncio
async def test_workflow_cron_parser(workflow_block):
    assert workflow_block._cron_next_wait("*/5 * * * *") == 300
    assert workflow_block._cron_next_wait("*/10 * * * *") == 600
    assert workflow_block._cron_next_wait("bad") == 300  # fallback


@pytest.mark.asyncio
async def test_a_failed_last_step_does_not_crash_the_run_summary(workflow_block):
    """New-shape test for the KeyError('result') found live.

    A failed step appends {"step_id", "block", "status", "error"} -- no
    "result" key -- and the run summary indexed step_results[-1]["result"]
    unconditionally. Any pipeline whose LAST step failed crashed the whole
    workflow block instead of reporting the failure it had already recorded.
    """
    result = await workflow_block.execute(
        {
            "pipeline_id": "crash-probe",
            "steps": [
                {"id": "s1", "block": "does_not_exist", "input": {}, "params": {}}
            ],
        },
        {"action": "run"},
    )
    # The block must ANSWER (with the failure recorded), not raise KeyError.
    assert result["block"] == "workflow"
    inner = result["result"]
    assert inner["status"] in ("partial", "failed")
    assert inner["final_output"] == {}
    step = inner["results"][-1]
    assert step["status"] == "failed"
    assert step.get("error")


@pytest.mark.asyncio
async def test_a_step_may_name_its_block_with_block_id(workflow_block):
    """Every consumer outside this repo (the CerebrumDev factory, block.json,
    the lockfile) calls the identifier block_id; a pipeline written in that
    vocabulary used to fail every step with "No block specified"."""
    result = await workflow_block.execute(
        {
            "pipeline_id": "alias-probe",
            "steps": [
                {"id": "s1", "block_id": "does_not_exist", "input": {}, "params": {}}
            ],
        },
        {"action": "run"},
    )
    step = result["result"]["results"][-1]
    # The block name RESOLVED (and then failed on the unknown block) --
    # proving the alias was read; the old code failed earlier with
    # "No block specified".
    assert step["status"] == "failed"
    assert step.get("error") != "No block specified"
