"""Skills Router — Dedicated REST endpoints for the skills block."""

from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.blocks import BLOCK_REGISTRY
from app.dependencies import block_instances, _create_block_instance, require_api_key

router = APIRouter()


class SkillsRequest(BaseModel):
    action: str = Field(default="hints", description="hints | validation | style | workflow | list | full")
    deliverable: Optional[str] = Field(default=None, description="xlsx | pdf | docx | pptx | webapp | backend | image-pdf | ifc-xlsx")
    workflow: Optional[str] = Field(default=None, description="drone_qaqc | bim_boq | progress_dashboard")
    input: Optional[Any] = Field(default=None, description="Deliverable type or query string")


async def _get_skills_block():
    if "skills" not in block_instances:
        block_instances["skills"] = _create_block_instance(BLOCK_REGISTRY["skills"])
    return block_instances["skills"]


@router.get("/skills/deliverables")
async def list_deliverables(auth: dict = Depends(require_api_key)):
    """List all supported deliverable types and workflows."""
    block = await _get_skills_block()
    result = await block.execute(None, {"action": "list"})
    if result.get("status") == "error":
        raise HTTPException(400, result.get("error"))
    return result


@router.post("/skills/hints")
async def get_hints(request: SkillsRequest, auth: dict = Depends(require_api_key)):
    """Get orchestrator hints for a deliverable or workflow."""
    block = await _get_skills_block()
    deliverable = request.deliverable or (str(request.input) if request.input else None)
    result = await block.execute(deliverable, {
        "action": "hints",
        "deliverable": deliverable,
        "workflow": request.workflow,
    })
    if result.get("status") == "error":
        raise HTTPException(400, result.get("error"))
    return result


@router.post("/skills/validation")
async def get_validation(request: SkillsRequest, auth: dict = Depends(require_api_key)):
    """Get validation rules for a deliverable type."""
    block = await _get_skills_block()
    deliverable = request.deliverable or (str(request.input) if request.input else None)
    result = await block.execute(deliverable, {
        "action": "validation",
        "deliverable": deliverable,
    })
    if result.get("status") == "error":
        raise HTTPException(400, result.get("error"))
    return result


@router.post("/skills/style")
async def get_style(request: SkillsRequest, auth: dict = Depends(require_api_key)):
    """Get style system for a deliverable type."""
    block = await _get_skills_block()
    deliverable = request.deliverable or (str(request.input) if request.input else None)
    result = await block.execute(deliverable, {
        "action": "style",
        "deliverable": deliverable,
    })
    if result.get("status") == "error":
        raise HTTPException(400, result.get("error"))
    return result


@router.post("/skills/workflow")
async def get_workflow(request: SkillsRequest, auth: dict = Depends(require_api_key)):
    """Get full workflow pipeline for a domain."""
    block = await _get_skills_block()
    workflow = request.workflow or request.deliverable or (str(request.input) if request.input else None)
    result = await block.execute(None, {
        "action": "workflow",
        "workflow": workflow,
    })
    if result.get("status") == "error":
        raise HTTPException(400, result.get("error"))
    return result
