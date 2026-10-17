"""Reactive workflow trigger API — register custom auto-chain triggers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.reactive_workflow import (
    WorkflowStep,
    WorkflowTriggerRegistration,
    get_reactive_engine,
)
from app.dependencies import require_api_key

router = APIRouter(prefix="/v1/workflows", tags=["workflows"])


class TriggerStepIn(BaseModel):
    block_id: str
    params: Dict[str, Any] = Field(default_factory=dict)
    input_mapping: Dict[str, str] = Field(default_factory=dict)


class TriggerRegisterRequest(BaseModel):
    event_type: str
    min_severity: Optional[str] = None
    steps: List[TriggerStepIn]
    enabled: bool = True
    description: str = ""


@router.get("/triggers")
async def list_workflow_triggers(auth: dict = Depends(require_api_key)):
    """List registered reactive workflow triggers (built-in + custom)."""
    engine = get_reactive_engine()
    return {"triggers": engine.list_triggers(), "total": len(engine.list_triggers())}


@router.post("/triggers")
async def register_workflow_trigger(
    request: TriggerRegisterRequest,
    auth: dict = Depends(require_api_key),
):
    """Register a custom reactive workflow trigger."""
    if not request.steps:
        raise HTTPException(status_code=400, detail="At least one workflow step is required")

    engine = get_reactive_engine()
    registration = WorkflowTriggerRegistration(
        event_type=request.event_type,
        min_severity=request.min_severity,
        steps=[WorkflowStep(**s.model_dump()) for s in request.steps],
        enabled=request.enabled,
        description=request.description,
    )
    engine.register_trigger(registration)
    return {"status": "registered", "trigger": registration.model_dump(mode="json")}


@router.delete("/triggers/{trigger_id}")
async def unregister_workflow_trigger(
    trigger_id: str,
    auth: dict = Depends(require_api_key),
):
    """Remove a custom trigger (built-in triggers cannot be removed)."""
    engine = get_reactive_engine()
    if not engine.unregister_trigger(trigger_id):
        raise HTTPException(status_code=404, detail=f"Trigger '{trigger_id}' not found or protected")
    return {"status": "removed", "trigger_id": trigger_id}
