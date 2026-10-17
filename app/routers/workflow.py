"""Workflow Router — Declarative pipeline execution endpoints."""

from typing import Any, Dict, List, Optional, Union
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.dependencies import require_api_key, get_block_instance

router = APIRouter()


class PipelineStep(BaseModel):
    id: str = Field(..., description="Step identifier")
    block: str = Field(..., description="Block name to execute")
    # Block inputs may be a dict, a string (e.g. plain prompt for chat/translate),
    # a list (e.g. batch of texts for vector_search), or null. Don't lock to dict.
    input: Optional[Union[Dict[str, Any], str, list]] = Field(default_factory=dict)
    params: Dict[str, Any] = Field(default_factory=dict)
    stop_on_error: bool = Field(default=True)
    break_on_error: bool = Field(default=False)


class PipelineTrigger(BaseModel):
    type: str = Field(default="manual", description="manual | cron | webhook")
    cron: Optional[str] = Field(default=None, description="Cron expression (e.g. */5 * * * *)")
    interval_seconds: Optional[int] = Field(default=None)


class PipelineRequest(BaseModel):
    pipeline_id: Optional[str] = Field(default=None)
    steps: List[PipelineStep] = Field(default_factory=list)
    trigger: PipelineTrigger = Field(default_factory=PipelineTrigger)
    timeout: int = Field(default=60)


class PipelineResponse(BaseModel):
    pipeline_id: str
    status: str
    run_id: str
    step_count: int
    results: List[Dict]
    execution_time_ms: int
    final_output: Dict


@router.post("/workflow/run", response_model=PipelineResponse)
async def workflow_run(request: PipelineRequest, auth: dict = Depends(require_api_key)):
    """Run a pipeline synchronously."""
    block = get_block_instance("workflow")
    payload = request.model_dump()
    result = await block.process(payload, {"action": "run"})

    if result.get("status") == "error":
        # Surface validation_errors / step errors so the caller can fix the
        # pipeline. The bare error string is unactionable on its own.
        from app.core.http_errors import classify_block_error
        err = result.get("error", "Pipeline failed")
        detail: Any = err
        if result.get("validation_errors"):
            detail = {"error": err, "validation_errors": result["validation_errors"]}
        raise HTTPException(status_code=classify_block_error(result), detail=detail)

    inner = result.get("result", result)
    return PipelineResponse(
        pipeline_id=inner.get("pipeline_id", ""),
        status=inner.get("status", "completed"),
        run_id=inner.get("run_id", ""),
        step_count=inner.get("step_count", 0),
        results=inner.get("results", []),
        execution_time_ms=inner.get("execution_time_ms", 0),
        final_output=inner.get("final_output", {}),
    )


@router.post("/workflow/schedule")
async def workflow_schedule(request: PipelineRequest, auth: dict = Depends(require_api_key)):
    """Schedule a pipeline to run recurringly."""
    block = get_block_instance("workflow")
    payload = request.model_dump()
    result = await block.process(payload, {"action": "schedule"})

    if result.get("status") == "error":
        from app.core.http_errors import classify_block_error
        err = result.get("error", "Scheduling failed")
        raise HTTPException(status_code=classify_block_error(result), detail=err)

    return result.get("result", result)


@router.post("/workflow/unschedule")
async def workflow_unschedule(pipeline_id: str, auth: dict = Depends(require_api_key)):
    """Unschedule a pipeline."""
    block = get_block_instance("workflow")
    result = await block.process({"pipeline_id": pipeline_id}, {"action": "unschedule"})
    return result.get("result", result)


@router.get("/workflow/list")
async def workflow_list(auth: dict = Depends(require_api_key)):
    """List all registered pipelines."""
    block = get_block_instance("workflow")
    result = await block.process(None, {"action": "list"})
    return result.get("result", result)


@router.get("/workflow/{pipeline_id}")
async def workflow_get(pipeline_id: str, auth: dict = Depends(require_api_key)):
    """Get a pipeline definition."""
    block = get_block_instance("workflow")
    result = await block.process({"pipeline_id": pipeline_id}, {"action": "get"})
    return result.get("result", result)


@router.get("/workflow/history/recent")
async def workflow_history(auth: dict = Depends(require_api_key)):
    """Get recent pipeline execution history."""
    block = get_block_instance("workflow")
    result = await block.process(None, {"action": "history"})
    return result.get("result", result)
