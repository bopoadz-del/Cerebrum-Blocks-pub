"""Agent Swarm Router — Multi-agent orchestration endpoints."""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.dependencies import require_api_key, get_block_instance

router = APIRouter()


class AgentConfig(BaseModel):
    name: str = Field(..., description="Unique agent identifier")
    role: str = Field(default="custom", description="Agent role: planner, researcher, coder, reviewer, executor")
    backstory: str = Field(default="", description="Personality/context prompt")
    goal: str = Field(default="", description="What this agent must achieve")
    llm_provider: Optional[str] = Field(default=None, description="Override global LLM (kimi)")
    model: Optional[str] = Field(default=None, description="Override model name")
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    tools: List[str] = Field(default_factory=list, description="Tool names this agent can use")
    allow_delegation: bool = Field(default=True)
    max_iterations: int = Field(default=5, ge=1, le=20)


class TaskConfig(BaseModel):
    id: str = Field(..., description="Task identifier")
    description: str = Field(..., description="What needs to be done")
    expected_output: str = Field(default="", description="Expected format/quality")
    agent: str = Field(..., description="Agent name assigned to this task")
    context: Optional[str] = Field(default=None, description="Additional context")
    dependencies: List[str] = Field(default_factory=list, description="Task IDs that must complete first")
    output_file: Optional[str] = Field(default=None, description="Where to save result")


class SwarmRequest(BaseModel):
    project_id: str = Field(default="default", description="Project identifier")
    objective: str = Field(..., description="High-level goal for the swarm")
    agents: List[AgentConfig] = Field(default_factory=list)
    tasks: List[TaskConfig] = Field(default_factory=list)
    llm_provider: Optional[str] = Field(default=None, description="Global LLM override")
    verbose: bool = Field(default=False)
    store_memory: bool = Field(default=True, description="Store results in vector DB")


class SwarmResponse(BaseModel):
    project_id: str
    status: str
    objective: str
    outputs: List[Dict]
    final_output: str
    total_tokens: int
    total_time_ms: int
    swarm_id: str
    memory_id: Optional[str] = None


@router.post("/swarm/execute", response_model=SwarmResponse)
async def execute_swarm(request: SwarmRequest, auth: dict = Depends(require_api_key)):
    """Execute a full agent swarm workflow synchronously.

    Example:
    ```json
    {
      "project_id": "demo-001",
      "objective": "Write a FastAPI auth endpoint",
      "agents": [
        {"name": "architect", "role": "planner", "goal": "Design API structure"},
        {"name": "coder", "role": "coder", "goal": "Implement the code"}
      ],
      "tasks": [
        {"id": "design", "description": "Design Pydantic models", "agent": "architect"},
        {"id": "implement", "description": "Write FastAPI code", "agent": "coder", "dependencies": ["design"]}
      ]
    }
    ```
    """
    block = get_block_instance("agent_swarm")
    payload = request.model_dump()
    result = await block.process(payload, {"action": "execute"})

    if result.get("status") == "error":
        from app.core.http_errors import classify_block_error
        err = result.get("error", "Swarm execution failed")
        raise HTTPException(status_code=classify_block_error(result), detail=err)

    inner = result.get("result", result)
    return SwarmResponse(
        project_id=inner.get("project_id", "default"),
        status=inner.get("status", "completed"),
        objective=inner.get("objective", ""),
        outputs=inner.get("outputs", []),
        final_output=inner.get("final_output", ""),
        total_tokens=inner.get("total_tokens", 0),
        total_time_ms=inner.get("total_time_ms", 0),
        swarm_id=inner.get("swarm_id", ""),
        memory_id=inner.get("memory_id"),
    )


@router.post("/swarm/execute/async")
async def execute_swarm_async(request: SwarmRequest, auth: dict = Depends(require_api_key)):
    """Fire-and-forget swarm execution. Returns job ID to poll status."""
    block = get_block_instance("agent_swarm")
    payload = request.model_dump()
    result = await block.process(payload, {"action": "execute_async"})

    if result.get("status") == "error":
        from app.core.http_errors import classify_block_error
        err = result.get("error", "Async execution failed")
        raise HTTPException(status_code=classify_block_error(result), detail=err)

    return result.get("result", result)


@router.get("/swarm/status/{job_id}")
async def get_swarm_status(job_id: str, auth: dict = Depends(require_api_key)):
    """Check status of an async swarm job."""
    block = get_block_instance("agent_swarm")
    result = await block.process(job_id, {"action": "status"})
    return result.get("result", result)


@router.get("/swarm/health")
async def swarm_health(auth: dict = Depends(require_api_key)):
    """Agent Swarm Block health check."""
    block = get_block_instance("agent_swarm")
    result = await block.process(None, {"action": "health"})
    return result.get("result", result)
