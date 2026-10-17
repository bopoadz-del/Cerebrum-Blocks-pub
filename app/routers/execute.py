import json
import logging
import subprocess
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import os

import httpx
from anyio import to_thread

from app.blocks import BLOCK_REGISTRY, get_block_capabilities
from app.dependencies import require_api_key
from app.dependencies import block_instances, get_block_instance
from app.core.grounding import (
    VERDICT_OUT_OF_SCOPE,
    check_scope_refusal,
    evaluate_grounding,
    persist_verdict,
)
from app.core.input_adapter import adapt_input
from app.core.security import enforce_block_access, enforce_tier_block_access
from app.core.trust_scope import enforce_trust_scope
from app.block_registry import registry_block_exists

logger = logging.getLogger(__name__)
router = APIRouter()

# Answer-producing blocks whose replies must carry a grounding verdict.
# aviation_chat_server runs its own gate in-block and persists its verdicts.
_GROUNDED_ANSWER_BLOCKS = {"chat", "knowledge"}
_ANSWER_FIELDS = ("answer", "text", "response")


def _grounding_sources(input_data: Any, result: Dict[str, Any]) -> list:
    sources = []
    if isinstance(input_data, dict):
        for key in ("context", "question", "message", "text", "conversation"):
            value = input_data.get(key)
            if value:
                sources.append(json.dumps(value) if not isinstance(value, str) else value)
    for value in (result.get("sources"), result.get("chunks"), result.get("results")):
        if value:
            sources.append(json.dumps(value) if not isinstance(value, str) else value)
    return sources


def _apply_grounding_stage(block_name: str, input_data: Any, response: Any) -> Any:
    """Mandatory grounding stage for answer-producing blocks.

    Blocked → the answer field is null; never a raw ungrounded fallback.
    Every verdict is persisted to the grounding audit store.
    """
    if block_name not in _GROUNDED_ANSWER_BLOCKS or not isinstance(response, dict):
        return response
    result = response.get("result")
    if not isinstance(result, dict):
        return response
    answer_field = next(
        (f for f in _ANSWER_FIELDS if isinstance(result.get(f), str) and result.get(f)),
        None,
    )
    if answer_field is None:
        return response

    query = ""
    if isinstance(input_data, dict):
        query = str(
            input_data.get("question") or input_data.get("message") or input_data.get("text") or ""
        )
    elif isinstance(input_data, str):
        query = input_data

    # Scope refusal precedes grounding: a refused question is never
    # answered, however grounded the corpus may be.
    refusal = check_scope_refusal(query)
    if refusal is not None:
        persist_verdict(
            {
                "surface": f"execute:{block_name}",
                "query": query[:500],
                "verdict": VERDICT_OUT_OF_SCOPE,
                "refusal_id": refusal["id"],
                "reasons": [refusal["reason"]],
            }
        )
        response["grounding"] = {
            "verdict": VERDICT_OUT_OF_SCOPE,
            "refusal_id": refusal["id"],
            "reasons": [refusal["reason"]],
        }
        result[answer_field] = None
        return response

    verdict = evaluate_grounding(
        result[answer_field],
        sources=_grounding_sources(input_data, result),
        query=query,
    )
    persist_verdict(
        {
            "surface": f"execute:{block_name}",
            "query": query[:500],
            "verdict": verdict["verdict"],
            "reasons": verdict["reasons"],
            "unsupported_figures": verdict["unsupported_figures"],
        }
    )
    response["grounding"] = {
        "verdict": verdict["verdict"],
        "reasons": verdict["reasons"],
        "unsupported_figures": verdict["unsupported_figures"],
    }
    result[answer_field] = verdict["allowed_response"]
    return response


def _run_registry_block(block_name: str, input_data: Any, params: Dict) -> dict:
    """Execute a block via its registry adapter using subprocess.
    
    Reads JSON from stdin, parses JSON stdout.
    Falls back to error dict if subprocess fails.
    """
    import os
    import sys

    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    registry_dir = os.path.join(project_root, "block_registry", block_name)
    adapter_path = os.path.join(registry_dir, "block.py")

    if not os.path.exists(adapter_path):
        return {"success": False, "error": f"Registry adapter not found for {block_name}"}

    payload = {"input": input_data}
    if params:
        payload.update(params)

    env = os.environ.copy()
    env["PYTHONPATH"] = project_root

    try:
        proc = subprocess.run(
            [sys.executable, adapter_path],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=60,
            cwd=project_root,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Block {block_name} timed out after 60s"}
    except Exception as e:
        return {"success": False, "error": f"Failed to run block {block_name}: {e}"}
    
    if proc.returncode != 0:
        return {"success": False, "error": proc.stderr or f"Block {block_name} exited with code {proc.returncode}"}
    
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"success": False, "error": f"Invalid JSON output from block {block_name}", "raw_output": proc.stdout}
    
    return result


class ExecuteRequest(BaseModel):
    block: str = Field(..., description="Block name (chat, pdf, ocr, voice, etc.)")
    input: Optional[Any] = Field(default=None, description="Input data for the block")
    params: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Block parameters")


def _get_sandbox_runner_url() -> str:
    return os.getenv("SANDBOX_RUNNER_URL", "http://localhost:8001").rstrip("/")


def should_run_out_of_process(block_name: str) -> bool:
    """Return True when ``block_name`` must be executed via the sandbox runner.

    Core blocks default to capability-based dispatch. Non-core blocks apply
    publisher tier policy: community and revoked publishers are always
    out-of-process; verified publishers follow capability safety.
    """
    return get_block_capabilities(block_name).must_run_out_of_process


async def _run_block_via_runner(block_name: str, input_data: Any, params: Dict) -> dict:
    """Execute a block out-of-process via the sandbox runner service."""
    url = f"{_get_sandbox_runner_url()}/run_block"
    payload = {
        "block_name": block_name,
        "input": input_data,
        "params": params or {},
        "timeout_s": 60,
    }
    try:
        async with httpx.AsyncClient(timeout=70) as client:
            response = await client.post(url, json=payload)
    except httpx.ConnectError as exc:
        logger.warning("sandbox runner unavailable at %s: %s", url, exc)
        raise HTTPException(503, f"Sandbox runner unavailable at {url}")
    except httpx.TimeoutException:
        raise HTTPException(504, f"Sandbox runner timed out for block '{block_name}'")

    if response.status_code >= 400:
        detail = response.text or f"Sandbox runner returned {response.status_code}"
        raise HTTPException(502, detail)

    runner_result = response.json()
    if runner_result.get("status") != "ok":
        error = runner_result.get("stderr") or runner_result.get("result") or "Sandbox execution failed"
        raise HTTPException(500, error)

    return {
        "block": block_name,
        "request_id": "sandbox",
        "status": "success",
        "result": runner_result.get("result", {}),
        "confidence": 1.0,
        "source_id": f"{block_name}-sandbox",
        "metadata": {"source": "sandbox-runner"},
        "processing_time_ms": runner_result.get("elapsed_ms", 0),
    }


async def _run_block(request: ExecuteRequest, auth: dict) -> dict:
    """Shared body for /execute and /v1/execute.

    Both routers do FastAPI auth themselves (Depends(require_api_key))
    and pass the resolved auth dict in. Previously /v1/execute called
    /execute as a coroutine, leaving execute()'s `auth` param at its
    default — the Depends sentinel — which then crashed
    enforce_block_access (`'Depends' object has no attribute 'get'`).

    Blocks with elevated capabilities (network, filesystem, privileged
    imports, cross-block access) are dispatched to the sandbox runner.
    Safe blocks run in-process as before.
    """
    block_name = request.block

    if block_name.startswith("container_"):
        raise HTTPException(400, f"Container '{block_name}' cannot be executed directly. Use Block Store.")

    if block_name not in BLOCK_REGISTRY and not registry_block_exists(block_name):
        raise HTTPException(404, f"Block '{block_name}' not found. Available: {list(BLOCK_REGISTRY.keys())}")

    enforce_block_access(block_name, auth)
    enforce_tier_block_access(block_name, auth)

    # Trust-scope enforcement (action-contract kernel, wired to the live
    # path): caller-supplied identity/permission scope never reaches a
    # block; the server-derived scope from the validated API key does.
    scoped_input, scoped_params, scope_warnings = enforce_trust_scope(
        request.input, request.params, auth
    )

    def _with_scope_warnings(response: dict) -> dict:
        if scope_warnings and isinstance(response, dict):
            meta = response.setdefault("metadata", {})
            if isinstance(meta, dict):
                meta["trust_scope_warnings"] = scope_warnings
        return _apply_grounding_stage(block_name, scoped_input, response)

    capabilities = get_block_capabilities(block_name)
    if capabilities.publisher_tier == "revoked":
        raise HTTPException(
            status_code=403,
            detail=f"Block '{block_name}' is from a revoked publisher and cannot be executed",
        )

    use_runner = capabilities.must_run_out_of_process

    if use_runner:
        return _with_scope_warnings(
            await _run_block_via_runner(block_name, scoped_input, scoped_params)
        )

    # In-process execution path for safe blocks.
    if block_name in BLOCK_REGISTRY:
        try:
            block = get_block_instance(block_name)
            adapted_input = adapt_input(scoped_input, block)
            return _with_scope_warnings(await block.execute(adapted_input, scoped_params))
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("block execution failed", extra={"block": block_name})
            from app.core.http_errors import classify_block_error
            err = f"Execution failed: {e}"
            status = classify_block_error(e)
            if status == 422:
                status = 500
            raise HTTPException(status, err)

    # Registry-only blocks with safe capabilities fall back to local subprocess.
    # subprocess.run blocks for up to 60s; run it in a worker thread so the
    # single uvicorn event loop (and with it /health and /ready) stays
    # responsive — same fix as the pre-warm offload in
    # app/dependencies.py::init_blocks.
    registry_result = await to_thread.run_sync(
        _run_registry_block, block_name, scoped_input, scoped_params
    )
    if registry_result.get("success"):
        return _with_scope_warnings({
            "block": block_name,
            "request_id": "registry",
            "status": "success",
            "result": registry_result.get("output", {}),
            "confidence": 1.0,
            "source_id": f"{block_name}-registry",
            "metadata": {"source": "registry"},
            "processing_time_ms": 0,
        })
    raise HTTPException(500, registry_result.get("error", "Registry execution failed"))


@router.post("/execute")
async def execute(request: ExecuteRequest, auth: dict = Depends(require_api_key)):
    """Execute a single block."""
    return await _run_block(request, auth)


@router.post("/v1/execute")
async def execute_v1(request: ExecuteRequest, auth: dict = Depends(require_api_key)):
    """Execute a single block (v1 API)."""
    return await _run_block(request, auth)
