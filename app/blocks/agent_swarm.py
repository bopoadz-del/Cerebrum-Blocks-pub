"""Agent Swarm Block — Multi-agent orchestrator for Cerebrum Blocks.

Lightweight async orchestrator. No heavy frameworks.
- Dependency resolution (topological sort)
- LLM: Kimi (Moonshot) only — the platform's single provider (OpenAI-compatible)
- Vector memory integration
- Standard Cerebrum block contract
- Tool-using agents via MCP contract + direct dispatch (no HTTP)
"""

import os
import time
import uuid
import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum

from app.core.universal_base import UniversalBlock
from app.core.typed_block import TypedBlock, Schema, ContentType
from app.core.http_errors import error_kind
from app.core.http_errors import mark_unavailable

logger = logging.getLogger(__name__)


# Cap on tool-call iterations within a single agent task. Without a cap a
# misbehaving LLM can loop forever; ~6 round-trips is plenty for any realistic
# task ("plan → call A → call B → summarise" fits in 4).
_MAX_TOOL_ITERATIONS = int(os.getenv("AGENT_MAX_TOOL_ITERATIONS", "6"))


class LLMProvider(str, Enum):
    # Kimi (Moonshot) is the platform's only LLM provider.
    KIMI = "kimi"


class AgentSwarmBlock(TypedBlock):
    """Universal agent swarm orchestrator."""

    name = "agent_swarm"
    version = "1.0.0"
    description = "Multi-agent task orchestration with dependency resolution and LLM routing"
    layer = 3
    tags = ["agents", "swarm", "orchestration", "ai", "multi-agent"]
    requires = ["vector_search"]

    input_schema = Schema(
        content_type=ContentType.JSON,
        required_fields=[],
        optional_fields=["objective", "project_id", "agents", "tasks", "llm_provider", "verbose", "store_memory"],
        format_hints={}
    )

    # Only "status" is guaranteed by every action (execute/async/health);
    # execute-specific fields are optional so the contract matches reality.
    output_schema = Schema(
        content_type=ContentType.JSON,
        required_fields=["status"],
        optional_fields=[
            "project_id", "objective", "outputs", "final_output",
            "total_tokens", "total_time_ms", "swarm_id", "memory_id",
            "job_id", "agents", "mode", "note",
        ],
        format_hints={}
    )

    accepted_input_types = ["JSON", "SwarmRequest"]
    produced_output_types = ["JSON", "SwarmResponse"]

    default_config = {
        "llm_provider": "kimi",
        "kimi_base_url": os.getenv("KIMI_BASE_URL", os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.ai/v1")),
        "kimi_model": os.getenv("KIMI_MODEL", os.getenv("MOONSHOT_MODEL", "kimi-k2-0905-preview")),
        "kimi_api_key": os.getenv("KIMI_API_KEY", os.getenv("MOONSHOT_API_KEY", "")),
        "vector_db_url": os.getenv("VECTOR_DB_URL", "http://localhost:8001"),
        "max_concurrent_agents": int(os.getenv("MAX_CONCURRENT_AGENTS", "5")),
        "default_timeout": int(os.getenv("DEFAULT_TIMEOUT", "120")),
        "store_memory": True,
    }

    ui_schema = {
        "input": {
            "type": "json",
            "accept": None,
            "placeholder": '{"objective": "Write a FastAPI endpoint", "agents": [...], "tasks": [...]}',
            "multiline": True,
        },
        "output": {
            "type": "json",
            "fields": [
                {"name": "project_id", "type": "text", "label": "Project ID"},
                {"name": "status", "type": "text", "label": "Status"},
                {"name": "final_output", "type": "text", "label": "Final Output"},
                {"name": "outputs", "type": "json", "label": "Agent Outputs"},
                {"name": "total_tokens", "type": "number", "label": "Total Tokens"},
                {"name": "total_time_ms", "type": "number", "label": "Time (ms)"},
            ],
        },
        "params": [
            {
                "name": "action",
                "type": "select",
                "label": "Action",
                "options": ["execute", "execute_async", "status", "health"],
                "default": "execute",
            },
            {"name": "max_concurrent_agents", "type": "number", "label": "Max Concurrent Agents", "default": 5},
            {"name": "default_timeout", "type": "number", "label": "Default Timeout", "default": 120},
        ],
        "quick_actions": [
            {"icon": "🐝", "label": "Run Swarm", "prompt": "Run agent swarm to solve this"},
            {"icon": "📋", "label": "Plan Tasks", "prompt": "Generate a task plan with agents"},
        ],
    }

    async def execute(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        action = params.get("action") if isinstance(params, dict) else None
        if isinstance(input_data, str):
            if action == "status":
                input_data = {"job_id": input_data}
            else:
                input_data = {"objective": input_data}
        return await super().execute(input_data, params)

    def validate_input(self, data: Any) -> Dict[str, Any]:
        if isinstance(data, dict) and data.get("action") in {"health", "status", "list", "history", "get", "unschedule", "broadcast", "search", "summarize", "structure", "execute_async"}:
            return {"valid": True, "errors": [], "warnings": [], "data": data}
        return super().validate_input(data)

    def __init__(self, hal_block=None, config: Dict = None):
        super().__init__(hal_block, config)
        self.semaphore = asyncio.Semaphore(self.config.get("max_concurrent_agents", 5))
        self.active_swarms: Dict[str, Dict] = {}
        self._job_store: Dict[str, Dict] = {}  # Simple in-memory job store for async

    # ── Public API ─────────────────────────────────────────────────────────────

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        """Main entry: accepts swarm request dict."""
        params = params or {}
        action = params.get("action", "execute")

        if action == "execute":
            return await self._execute_swarm(input_data, params)
        elif action == "execute_async":
            return await self._execute_swarm_async(input_data, params)
        elif action == "status":
            return self._get_job_status(input_data)
        elif action == "health":
            return await self._health_check()
        else:
            return {"status": "error", "error": f"Unknown action: {action}"}

    # ── Core Execution ─────────────────────────────────────────────────────────

    async def _execute_swarm(self, input_data: Any, params: Dict) -> Dict:
        """Synchronous swarm execution (waits for all tasks)."""
        request = self._normalize_request(input_data)
        project_id = request.get("project_id", "default")
        objective = request.get("objective", "")
        agents = request.get("agents", [])
        tasks = request.get("tasks", [])
        store_memory = request.get("store_memory", self.config.get("store_memory", True))
        llm_provider = request.get("llm_provider", self.config.get("llm_provider", "kimi"))

        if not agents or not tasks:
            # Return a demo/example response so the block works end-to-end
            return {
                "status": "success",
                "mode": "demo",
                "note": "No agents/tasks provided. Below is a demo of swarm output format.",
                "project_id": project_id,
                "objective": objective or "Demo swarm execution",
                "agents_executed": 2,
                "tasks_completed": 3,
                "results": [
                    {"agent": "estimator", "task": "calculate_concrete", "status": "done", "output": "Concrete volume: 125 m³"},
                    {"agent": "scheduler", "task": "check_float", "status": "done", "output": "Total float: 14 days"},
                    {"agent": "qa_engineer", "task": "review_spec", "status": "done", "output": "3 non-compliance items found"},
                ],
                "outputs": [],
                "final_output": (
                    "DEMO ONLY — no agents/tasks were provided, so nothing was "
                    "executed. Provide agents and tasks for real execution."
                ),
                "summary": "Demo swarm completed successfully. Provide agents and tasks for real execution.",
            }

        # Validate agents
        agent_names = {a["name"] for a in agents}
        for task in tasks:
            if task.get("agent") not in agent_names:
                return {
                    "status": "error",
                    "error": f"Task '{task.get('id')}' assigned to unknown agent '{task.get('agent')}'"
                }

        swarm_id = str(uuid.uuid4())[:8]
        start_time = time.time()
        agent_map = {a["name"]: a for a in agents}

        # Topological sort
        task_order = self._resolve_dependencies(tasks)
        completed_tasks: Dict[str, Dict] = {}
        outputs: List[Dict] = []

        try:
            for wave in task_order:
                wave_tasks = [t for t in tasks if t["id"] in wave]
                coros = [
                    self._execute_task(t, agent_map.get(t["agent"]), completed_tasks, llm_provider)
                    for t in wave_tasks
                ]
                results = await asyncio.gather(*coros, return_exceptions=True)

                for task, result in zip(wave_tasks, results):
                    if isinstance(result, Exception):
                        output = {
                            "agent": task["agent"],
                            "task_id": task["id"],
                            "status": "failed",
                            "result": str(result),
                            "tokens_used": 0,
                            "execution_time_ms": 0,
                            "metadata": {"error_type": type(result).__name__},
                        }
                    else:
                        output = result
                        completed_tasks[task["id"]] = output
                    outputs.append(output)

            successful = [o for o in outputs if o["status"] == "completed"]
            final_output = "\n\n---\n\n".join([o["result"] for o in successful])
            total_tokens = sum(o.get("tokens_used", 0) for o in outputs)
            total_time_ms = int((time.time() - start_time) * 1000)
            status = "completed" if all(o["status"] == "completed" for o in outputs) else "partial"

            response = {
                "status": status,
                "project_id": project_id,
                "objective": objective,
                "outputs": outputs,
                "final_output": final_output,
                "total_tokens": total_tokens,
                "total_time_ms": total_time_ms,
                "swarm_id": swarm_id,
            }

            if store_memory:
                memory_id = await self._store_in_vector_db(swarm_id, project_id, objective, outputs, final_output, status)
                response["memory_id"] = memory_id

            return response

        except Exception as e:
            return {"status": "error", "error": str(e), "error_kind": error_kind(e), "swarm_id": swarm_id}

    async def _execute_swarm_async(self, input_data: Any, params: Dict) -> Dict:
        """Fire-and-forget: queue swarm and return job ID."""
        job_id = str(uuid.uuid4())[:8]
        self._job_store[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "created_at": time.time(),
            "result": None,
        }

        # Launch in background
        asyncio.create_task(self._run_async_job(job_id, input_data, params))

        return {
            "status": "queued",
            "job_id": job_id,
            "check_url": f"/swarm/status/{job_id}",
        }

    async def _run_async_job(self, job_id: str, input_data: Any, params: Dict):
        self._job_store[job_id]["status"] = "running"
        try:
            result = await self._execute_swarm(input_data, params)
            self._job_store[job_id]["status"] = result.get("status", "completed")
            self._job_store[job_id]["result"] = result
        except Exception as e:
            self._job_store[job_id]["status"] = "failed"
            self._job_store[job_id]["result"] = {"status": "error", "error": str(e), "error_kind": error_kind(e)}

    def _get_job_status(self, job_id: str) -> Dict:
        if isinstance(job_id, dict):
            job_id = job_id.get("job_id", "")
        job = self._job_store.get(job_id)
        if not job:
            return {"status": "error", "error": f"Job {job_id} not found"}
        return {
            "status": job["status"],
            "job_id": job_id,
            "result": job.get("result"),
        }

    # ── Task Execution ─────────────────────────────────────────────────────────

    async def _execute_task(
        self,
        task: Dict,
        agent: Optional[Dict],
        completed_tasks: Dict[str, Dict],
        global_provider: str,
    ) -> Dict:
        async with self.semaphore:
            start = time.time()
            task_id = task.get("id", "unknown")
            agent_name = task.get("agent", "unknown")

            if not agent:
                return {
                    "agent": agent_name,
                    "task_id": task_id,
                    "status": "failed",
                    "result": "Agent config not found",
                    "tokens_used": 0,
                    "execution_time_ms": 0,
                    "metadata": {},
                }

            # Build context from dependencies
            context_parts = []
            if task.get("context"):
                context_parts.append(task["context"])
            for dep_id in task.get("dependencies", []):
                if dep_id in completed_tasks:
                    dep = completed_tasks[dep_id]
                    context_parts.append(f"[Task {dep_id} output]:\n{dep['result']}")

            full_context = "\n\n".join(context_parts) if context_parts else ""

            tool_specs, tool_block_map = self._build_agent_toolset(agent)
            tool_hint = (
                f"\n\nYou have access to these tools (call them when useful, "
                f"otherwise answer directly): {[t['function']['name'] for t in tool_specs]}"
                if tool_specs else ""
            )

            system_prompt = (
                f"You are {agent.get('name', 'Agent')}, a {agent.get('role', 'custom')} agent.\n"
                f"Backstory: {agent.get('backstory', '')}\n"
                f"Goal: {agent.get('goal', '')}\n\n"
                f"Your task: {task.get('description', '')}\n"
                f"Expected output: {task.get('expected_output', '')}\n"
                f"{full_context}"
                f"{tool_hint}"
            )
            messages: List[Dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Execute this task and return only the final result.\n\n{task.get('description', '')}"},
            ]

            provider = agent.get("llm_provider") or global_provider
            model = agent.get("model")
            temperature = agent.get("temperature", 0.3)

            try:
                result = await self._run_agent_loop(
                    messages=messages,
                    provider=provider,
                    model=model,
                    temperature=temperature,
                    tool_specs=tool_specs,
                    tool_block_map=tool_block_map,
                )
                return {
                    "agent": agent_name,
                    "task_id": task_id,
                    "status": "completed",
                    "result": result["content"],
                    "tokens_used": result.get("tokens", 0),
                    "execution_time_ms": int((time.time() - start) * 1000),
                    "metadata": {
                        "model": result.get("model"),
                        "provider": result.get("provider"),
                        "tool_calls": result.get("tool_calls", []),
                        "iterations": result.get("iterations", 1),
                    },
                }
            except Exception as e:
                logger.exception("agent_swarm: task %s failed", task_id)
                return {
                    "agent": agent_name,
                    "task_id": task_id,
                    "status": "failed",
                    "result": str(e),
                    "tokens_used": 0,
                    "execution_time_ms": int((time.time() - start) * 1000),
                    "metadata": {"error": str(e), "error_kind": error_kind(e)},
                }

    # ── MCP-contract tool calling ─────────────────────────────────────────────

    def _build_agent_toolset(
        self, agent: Dict
    ) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
        """Filter the global MCP registry down to this agent's allowlist.

        agent['tools'] can be either:
          - block names ("construction") — exposes that block's tools
          - explicit MCP tool names ("construction_execute") — exact match
          - omitted/empty — agent runs without tools (LLM-only, current default)

        Returns:
            (tool_specs_for_llm, tool_name → block_name map)
            tool_specs are in OpenAI-compatible {type:"function", function:{...}}
            shape — Kimi (Moonshot) accepts this.
        """
        allowed = agent.get("tools") or []
        if not allowed:
            return [], {}

        # Resolve only the blocks this agent needs — calling get_all_schemas()
        # would import every registered block module (≈100MB of sklearn/sympy/
        # ezdxf/etc. on a Render starter dyno).
        from app.blocks import BLOCK_REGISTRY
        from app.core.mcp_registry import mcp_registry

        # Items in `allowed` are either block names or exact tool names. Map
        # each candidate back to a block name we can fetch the schema for.
        wanted_blocks: set = set()
        wanted_tool_names: set = set()
        for item in allowed:
            if item in BLOCK_REGISTRY:
                wanted_blocks.add(item)
            else:
                # Treat as a tool name; tool naming convention is "<block>_execute"
                # for the default mcp_tools() shape, so peel off the suffix.
                wanted_tool_names.add(item)
                if item.endswith("_execute"):
                    candidate = item[: -len("_execute")]
                    if candidate in BLOCK_REGISTRY:
                        wanted_blocks.add(candidate)

        tool_specs: List[Dict[str, Any]] = []
        tool_block_map: Dict[str, str] = {}

        for block_name in wanted_blocks:
            try:
                schema = mcp_registry.get_block_schema(block_name)
            except Exception:
                logger.exception("agent_swarm: schema unavailable for block %s", block_name)
                continue

            for tool in schema.get("tools", []):
                tool_name = tool.get("name")
                if not tool_name:
                    continue
                # If the agent specified a specific tool name and this block's
                # tool isn't it, skip — only matters when allowlist mixes block
                # names and tool names.
                if (
                    block_name not in (agent.get("tools") or [])
                    and tool_name not in wanted_tool_names
                ):
                    continue
                tool_specs.append({
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": tool.get("description", ""),
                        "parameters": tool.get("inputSchema") or {"type": "object", "properties": {}},
                    },
                })
                tool_block_map[tool_name] = block_name

        return tool_specs, tool_block_map

    async def _call_tool_direct(
        self, tool_name: str, args: Dict[str, Any], tool_block_map: Dict[str, str]
    ) -> Dict[str, Any]:
        """Dispatch an LLM tool_call to a block via direct .execute().

        MCP defines the contract; dispatch is in-process. Saves the ~3ms
        per-call HTTP overhead measured between TestClient and direct calls,
        which adds up across multi-step tool loops.
        """
        block_name = tool_block_map.get(tool_name)
        if not block_name:
            return {"error": f"tool '{tool_name}' not allowed for this agent"}

        from app.dependencies import get_block_instance

        try:
            block = get_block_instance(block_name)
        except Exception as e:
            logger.exception("agent_swarm: failed to resolve block %s", block_name)
            return {"error": f"block '{block_name}' could not be loaded: {e}"}

        input_data = args.get("input")
        if input_data is None:
            # If the LLM passed everything flat (no "input" wrapper), treat
            # the whole args object as input — minus our reserved "params"
            input_data = {k: v for k, v in args.items() if k != "params"} or {}
        params = args.get("params") or {}

        try:
            result = await block.execute(input_data, params)
        except Exception as e:
            logger.exception("agent_swarm: block %s raised", block_name)
            return {"error": f"block raised: {e}"}

        # Strip envelope so the LLM sees the inner result
        return result.get("result", result) if isinstance(result, dict) else {"value": result}

    async def _run_agent_loop(
        self,
        messages: List[Dict[str, Any]],
        provider: str,
        model: Optional[str],
        temperature: float,
        tool_specs: List[Dict[str, Any]],
        tool_block_map: Dict[str, str],
    ) -> Dict[str, Any]:
        """Tool-calling loop: chat → tool_calls → dispatch → chat → ...

        Falls back to a single chat call if the agent has no tools, preserving
        backwards compatibility with the previous "talking head" behaviour.
        """
        if not tool_specs:
            single = await self._llm_chat(
                messages=messages, provider=provider, model=model, temperature=temperature,
            )
            return {**single, "tool_calls": [], "iterations": 1}

        executed_calls: List[Dict[str, Any]] = []
        total_tokens = 0
        last_meta: Dict[str, Any] = {}

        for iteration in range(1, _MAX_TOOL_ITERATIONS + 1):
            response = await self._llm_chat(
                messages=messages,
                provider=provider,
                model=model,
                temperature=temperature,
                tools=tool_specs,
            )
            total_tokens += response.get("tokens", 0)
            last_meta = response

            tool_calls = response.get("tool_calls") or []
            if not tool_calls:
                # LLM produced a final answer — done.
                return {
                    "content": response.get("content", ""),
                    "model": response.get("model"),
                    "provider": response.get("provider"),
                    "tokens": total_tokens,
                    "tool_calls": executed_calls,
                    "iterations": iteration,
                }

            # Record the assistant turn with its tool_calls so the LLM can
            # match its tool_call_ids against our results.
            messages.append({
                "role": "assistant",
                "content": response.get("content") or "",
                "tool_calls": tool_calls,
            })

            for tc in tool_calls:
                tc_id = tc.get("id", f"call-{len(executed_calls)+1}")
                fn = tc.get("function", {}) if isinstance(tc.get("function"), dict) else {}
                tname = fn.get("name", "")
                raw_args = fn.get("arguments", "{}")
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                except json.JSONDecodeError:
                    args = {}

                tool_result = await self._call_tool_direct(tname, args, tool_block_map)
                executed_calls.append({"tool": tname, "args": args, "result": tool_result})

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "name": tname,
                    "content": json.dumps(tool_result, default=str)[:8000],
                })

        # Iteration cap hit — return whatever the last assistant message said.
        return {
            "content": last_meta.get("content", "") or "Iteration cap reached without final answer.",
            "model": last_meta.get("model"),
            "provider": last_meta.get("provider"),
            "tokens": total_tokens,
            "tool_calls": executed_calls,
            "iterations": _MAX_TOOL_ITERATIONS,
            "iteration_cap_hit": True,
        }

    # ── Dependency Resolution ──────────────────────────────────────────────────

    def _resolve_dependencies(self, tasks: List[Dict]) -> List[List[str]]:
        """Topological sort — returns waves of task IDs."""
        task_map = {t["id"]: t for t in tasks}
        pending = set(t["id"] for t in tasks)
        waves = []

        while pending:
            ready = [
                tid for tid in pending
                if all(d in task_map and d not in pending for d in task_map[tid].get("dependencies", []))
            ]
            if not ready:
                ready = list(pending)  # Circular — force break
            waves.append(ready)
            for tid in ready:
                pending.remove(tid)

        return waves

    # ── LLM Routing ────────────────────────────────────────────────────────────

    async def _llm_chat(
        self,
        messages: List[Dict],
        provider: str,
        model: Optional[str] = None,
        temperature: float = 0.3,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict:
        import httpx  # noqa: F401  (used by the provider helper)

        # Kimi (Moonshot) only. Its cloud API is OpenAI-compatible, so the
        # swarm's tool-calling loop reaches it through _openai_compatible_chat.
        base = (self.config.get("kimi_base_url") or "https://api.moonshot.ai/v1").rstrip("/")
        return await self._openai_compatible_chat(
            messages=messages,
            model=model or self.config.get("kimi_model", "kimi-k2-0905-preview"),
            temperature=temperature,
            tools=tools,
            api_key=(
                self.config.get("kimi_api_key")
                or os.getenv("KIMI_API_KEY")
                or os.getenv("MOONSHOT_API_KEY", "")
            ),
            url=f"{base}/chat/completions",
            provider_label="kimi",
        )


    async def _openai_compatible_chat(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        temperature: float,
        tools: Optional[List[Dict[str, Any]]],
        api_key: str,
        url: str,
        provider_label: str,
    ) -> Dict[str, Any]:
        """Single OpenAI-format chat call — used for Kimi (Moonshot).

        Kimi's cloud API accepts the OpenAI {messages, tools, tool_choice} shape
        and returns {choices: [{message: {content, tool_calls}}]}.
        """
        import httpx
        if not api_key:
            raise mark_unavailable(ValueError(f"{provider_label} API key not configured"))
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        message = data["choices"][0]["message"]
        return {
            "content": message.get("content", "") or "",
            "tool_calls": message.get("tool_calls") or [],
            "model": model,
            "provider": provider_label,
            "tokens": data.get("usage", {}).get("total_tokens", 0),
        }


    # ── Vector Memory ──────────────────────────────────────────────────────────

    async def _store_in_vector_db(
        self,
        swarm_id: str,
        project_id: str,
        objective: str,
        outputs: List[Dict],
        final_output: str,
        status: str,
    ) -> Optional[str]:
        vector_block = self.get_dep("vector_search")
        collection = "cerebrum_swarm"
        content = f"Objective: {objective}\n\n{final_output}"
        metadata = {
            "swarm_id": swarm_id,
            "project_id": project_id,
            "objective": objective,
            "agents": json.dumps(list({o["agent"] for o in outputs})),
            "tasks": json.dumps([o["task_id"] for o in outputs]),
            "status": status,
        }

        if vector_block:
            try:
                result = await vector_block.process(
                    {"documents": [content], "metadatas": [metadata], "ids": [swarm_id]},
                    {"operation": "add", "collection": collection},
                )
                if result.get("status") == "success":
                    return swarm_id
            except Exception:
                pass

        # Fallback HTTP
        return await self._store_chroma_http(swarm_id, content, metadata, collection)

    async def _store_chroma_http(self, doc_id: str, document: str, metadata: Dict, collection: str) -> Optional[str]:
        import httpx
        db_url = self.config.get("vector_db_url", "")
        if not db_url:
            return None
        try:
            payload = {
                "collection": collection,
                "documents": [document],
                "metadatas": [metadata],
                "ids": [doc_id],
            }
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(f"{db_url}/api/v1/collections/add", json=payload)
                if resp.status_code == 200:
                    return doc_id
        except Exception:
            pass
        return None

    # ─- Health ─────────────────────────────────────────────────────────────────

    async def _health_check(self) -> Dict:
        llm_ready = await self._check_llm_health()
        return {
            "status": "healthy" if llm_ready else "degraded",
            "block_id": self.name,
            "version": self.version,
            "llm_provider": self.config.get("llm_provider", "kimi"),
            "llm_ready": llm_ready,
        }

    async def _check_llm_health(self) -> bool:
        # Kimi (Moonshot) only: healthy when an API key is configured.
        return bool(
            self.config.get("kimi_api_key")
            or os.getenv("KIMI_API_KEY")
            or os.getenv("MOONSHOT_API_KEY", "")
        )

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _normalize_request(self, input_data: Any) -> Dict:
        """Ensure input is a valid swarm request dict."""
        if isinstance(input_data, dict):
            req = input_data
        elif isinstance(input_data, str):
            try:
                req = json.loads(input_data)
            except json.JSONDecodeError:
                req = {"objective": input_data, "agents": [], "tasks": []}
        else:
            req = {"objective": str(input_data), "agents": [], "tasks": []}
        
        # Auto-assign IDs to tasks that don't have them
        for i, task in enumerate(req.get("tasks", [])):
            if isinstance(task, dict) and "id" not in task:
                task["id"] = f"task_{i}"
        
        return req
