"""Workflow / Pipeline Block — Chain Cerebrum blocks declaratively.

YAML/JSON pipeline definitions. Variable interpolation between steps.
Supports manual, webhook, and cron triggers.
"""

import os
import time
import uuid
import json
import logging
import re
import asyncio
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from app.core.universal_base import UniversalBlock
from app.core.typed_block import TypedBlock, Schema, ContentType
from app.core.http_errors import error_kind

logger = logging.getLogger(__name__)


class WorkflowBlock(TypedBlock):
    """Declarative pipeline orchestrator for Cerebrum Blocks."""

    name = "workflow"
    version = "1.0.0"
    description = "Chain blocks into pipelines with variable interpolation and scheduling"
    layer = 2
    tags = ["workflow", "pipeline", "orchestration", "automation", "core"]
    requires = []

    input_schema = Schema(
        content_type=ContentType.JSON,
        required_fields=["steps"],
        optional_fields=["pipeline_id", "trigger", "timeout"],
        format_hints={}
    )

    # Only "status" is guaranteed by every action (run/list/get/history/health);
    # run-specific fields are optional so the contract matches reality.
    output_schema = Schema(
        content_type=ContentType.JSON,
        required_fields=["status"],
        optional_fields=[
            "pipeline_id", "run_id", "step_count", "results",
            "execution_time_ms", "final_output", "pipelines", "runs",
            "workflows", "steps",
        ],
        format_hints={}
    )

    accepted_input_types = ["JSON", "PipelineDefinition"]
    produced_output_types = ["JSON", "PipelineResult"]


    default_config = {
        "max_pipeline_steps": int(os.getenv("MAX_PIPELINE_STEPS", "20")),
        "enable_scheduler": os.getenv("ENABLE_WORKFLOW_SCHEDULER", "true").lower() == "true",
        "default_timeout": int(os.getenv("WORKFLOW_STEP_TIMEOUT", "60")),
    }

    ui_schema = {
        "input": {
            "type": "json",
            "accept": None,
            "placeholder": '{"pipeline_id": "daily-report", "steps": [...]}',
            "multiline": True,
        },
        "output": {
            "type": "json",
            "fields": [
                {"name": "pipeline_id", "type": "text", "label": "Pipeline ID"},
                {"name": "status", "type": "text", "label": "Status"},
                {"name": "results", "type": "json", "label": "Step Results"},
                {"name": "execution_time_ms", "type": "number", "label": "Time (ms)"},
            ],
        },
        "params": [
            {
                "name": "action",
                "type": "select",
                "label": "Action",
                "options": ["run", "schedule", "unschedule", "list", "get", "history", "status", "health"],
                "default": "run",
            },
            {"name": "max_pipeline_steps", "type": "number", "label": "Max Pipeline Steps", "default": 20},
            {"name": "enable_scheduler", "type": "boolean", "label": "Enable Scheduler", "default": True},
            {"name": "default_timeout", "type": "number", "label": "Default Timeout", "default": 60},
        ],
        "quick_actions": [
            {"icon": "⏩", "label": "Run Pipeline", "prompt": "Run a pipeline"},
            {"icon": "📅", "label": "Schedule", "prompt": "Schedule a recurring pipeline"},
        ],
    }


    async def execute(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        action = params.get("action") if isinstance(params, dict) else None
        if isinstance(input_data, str):
            if action in {"get", "unschedule"}:
                input_data = {"pipeline_id": input_data}
            else:
                input_data = {"steps": [{"id": "s1", "block": input_data}]}
        return await super().execute(input_data, params)

    def validate_input(self, data: Any) -> Dict[str, Any]:
        if isinstance(data, dict) and data.get("action") in {"health", "status", "list", "history", "get", "unschedule", "broadcast", "search", "summarize", "structure", "execute_async"}:
            return {"valid": True, "errors": [], "warnings": [], "data": data}
        return super().validate_input(data)

    def __init__(self, hal_block=None, config: Dict = None):
        super().__init__(hal_block, config)
        self._pipelines: Dict[str, Dict] = {}
        self._scheduled_tasks: Dict[str, asyncio.Task] = {}
        self._execution_history: List[Dict] = []

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        action = params.get("action", "run")

        if action == "run":
            return await self._run_pipeline(input_data, params)
        elif action == "schedule":
            return await self._schedule_pipeline(input_data, params)
        elif action == "unschedule":
            return self._unschedule_pipeline(input_data)
        elif action == "list":
            return self._list_pipelines()
        elif action == "get":
            return self._get_pipeline(input_data)
        elif action == "history":
            return self._get_history()
        elif action in ("status", "health"):
            return {"status": "success", "workflows": len(getattr(self, "_workflows", {}))}
        return {"status": "error", "error": f"Unknown action: {action}"}

    # ── Core Execution ─────────────────────────────────────────────────────────

    async def _validate_chain(self, steps: List[Dict]) -> List[str]:
        """Validate that step outputs match next step inputs using block schemas."""
        errors = []
        from app.blocks import BLOCK_REGISTRY

        for i in range(len(steps) - 1):
            current_name = steps[i].get("block")
            next_name = steps[i + 1].get("block")

            current_cls = BLOCK_REGISTRY.get(current_name)
            next_cls = BLOCK_REGISTRY.get(next_name)

            if not current_cls or not next_cls:
                errors.append(f"Step {i}: block '{current_name}' or '{next_name}' not found in registry")
                continue

            # Both blocks must declare typed schemas to be statically validated.
            # Untyped blocks are common in this platform — skip them rather than
            # rejecting the chain (the runtime will just pass values through).
            if not hasattr(current_cls, 'output_schema') or not current_cls.output_schema:
                continue
            if not hasattr(next_cls, 'input_schema') or not next_cls.input_schema:
                continue

            current_schema = current_cls.output_schema
            next_schema = next_cls.input_schema

            # Extract required/optional fields
            def get_fields(schema):
                if hasattr(schema, 'required_fields') and hasattr(schema, 'optional_fields'):
                    return set(schema.required_fields or []) | set(schema.optional_fields or [])
                elif isinstance(schema, dict):
                    props = schema.get("properties", {})
                    return set(props.keys())
                return set()

            current_fields = get_fields(current_schema)
            next_fields_required = set(next_schema.required_fields or []) if hasattr(next_schema, 'required_fields') else set()

            # Check if next step's required inputs are satisfied by current step's output
            missing = next_fields_required - current_fields
            if missing:
                errors.append(
                    f"Step {i+1} ('{next_name}'): requires fields {sorted(missing)} "
                    f"but '{current_name}' output only provides {sorted(current_fields)}"
                )

            # Content type compatibility warning
            current_type = getattr(current_schema, 'content_type', None)
            next_type = getattr(next_schema, 'content_type', None)
            if current_type and next_type and current_type != next_type:
                if next_type.value not in ['json', 'text', 'unknown']:
                    errors.append(
                        f"Step {i+1}: type mismatch — '{current_name}' produces '{current_type.value}' "
                        f"but '{next_name}' expects '{next_type.value}'"
                    )

        return errors

    async def _run_pipeline(self, input_data: Any, params: Dict) -> Dict:
        definition = self._normalize_definition(input_data)
        pipeline_id = definition.get("pipeline_id") or str(uuid.uuid4())[:8]
        definition["pipeline_id"] = pipeline_id
        self._pipelines[pipeline_id] = definition
        steps = definition.get("steps", [])
        timeout = definition.get("timeout", self.config.get("default_timeout", 60))

        if not steps:
            return {"status": "error", "error": "No steps defined"}

        if len(steps) > self.config.get("max_pipeline_steps", 20):
            return {"status": "error", "error": f"Max {self.config.get('max_pipeline_steps')} steps allowed"}

        # PRE-FLIGHT CHAIN VALIDATION
        chain_errors = await self._validate_chain(steps)
        if chain_errors:
            return {
                "status": "error",
                "error": "Chain validation failed — incompatible blocks",
                "validation_errors": chain_errors,
                "pipeline_id": pipeline_id,
            }

        start_time = time.time()
        context = {"pipeline_id": pipeline_id, "steps": {}}
        step_results = []
        overall_status = "completed"

        for idx, step in enumerate(steps):
            step_id = step.get("id", f"step_{idx}")
            # "block_id" accepted as an alias: every consumer outside this
            # repo (the CerebrumDev factory, block.json, the lockfile) calls
            # the identifier block_id, so pipelines written against that
            # vocabulary failed here with "No block specified".
            block_name = step.get("block") or step.get("block_id")
            step_input = step.get("input", {})
            step_params = step.get("params", {})

            if not block_name:
                step_results.append({
                    "step_id": step_id,
                    "status": "failed",
                    "error": "No block specified",
                })
                overall_status = "partial"
                continue

            # Interpolate variables
            try:
                step_input = self._interpolate(step_input, context)
                step_params = self._interpolate(step_params, context)
            except Exception as e:
                step_results.append({
                    "step_id": step_id,
                    "status": "failed",
                    "error": f"Interpolation error: {e}",
                })
                overall_status = "partial"
                continue

            # Execute block
            try:
                from app.blocks import BLOCK_REGISTRY
                block_cls = BLOCK_REGISTRY.get(block_name)
                if not block_cls:
                    step_results.append({
                        "step_id": step_id,
                        "status": "failed",
                        "error": f"Block '{block_name}' not found",
                    })
                    overall_status = "partial"
                    continue

                block = block_cls()
                result = await asyncio.wait_for(
                    block.execute(step_input, step_params),
                    timeout=timeout,
                )

                context["steps"][step_id] = result
                step_results.append({
                    "step_id": step_id,
                    "block": block_name,
                    "status": result.get("status", "unknown"),
                    "result": result,
                })

                if result.get("status") == "error" and step.get("stop_on_error", True):
                    overall_status = "partial"
                    if step.get("break_on_error", False):
                        break

            except asyncio.TimeoutError:
                step_results.append({
                    "step_id": step_id,
                    "block": block_name,
                    "status": "failed",
                    "error": f"Timeout after {timeout}s",
                })
                overall_status = "partial"
            except Exception as e:
                step_results.append({
                    "step_id": step_id,
                    "block": block_name,
                    "status": "failed",
                    "error": str(e), "error_kind": error_kind(e),
                })
                overall_status = "partial"

        execution_time_ms = int((time.time() - start_time) * 1000)
        run_record = {
            "run_id": str(uuid.uuid4())[:8],
            "pipeline_id": pipeline_id,
            "status": overall_status,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "execution_time_ms": execution_time_ms,
            "step_results": step_results,
        }
        self._execution_history.append(run_record)
        self._execution_history = self._execution_history[-100:]  # Keep last 100

        return {
            "status": overall_status,
            "pipeline_id": pipeline_id,
            "run_id": run_record["run_id"],
            "step_count": len(steps),
            "results": step_results,
            "execution_time_ms": execution_time_ms,
            # .get, not []: a FAILED last step's entry carries status/error and
            # no "result" key, and the whole run summary used to KeyError on
            # it — measured live when a factory-built platform ran a pipeline
            # whose only step failed. The caller still sees the failure via
            # "status" and the step's own error entry.
            "final_output": step_results[-1].get("result", {}) if step_results else {},
        }

    # ── Scheduling ─────────────────────────────────────────────────────────────

    async def _schedule_pipeline(self, input_data: Any, params: Dict) -> Dict:
        if not self.config.get("enable_scheduler", True):
            return {"status": "error", "error": "Scheduler disabled"}

        definition = self._normalize_definition(input_data)
        pipeline_id = definition.get("pipeline_id")
        cron = definition.get("trigger", {}).get("cron")
        interval = definition.get("trigger", {}).get("interval_seconds")

        if not pipeline_id:
            return {"status": "error", "error": "pipeline_id required for scheduling"}

        if not cron and not interval:
            return {"status": "error", "error": "Schedule requires cron or interval_seconds"}

        # Store definition
        self._pipelines[pipeline_id] = definition

        # Cancel existing task if any
        if pipeline_id in self._scheduled_tasks:
            self._scheduled_tasks[pipeline_id].cancel()

        # Start new task
        task = asyncio.create_task(self._scheduler_loop(pipeline_id, cron, interval))
        self._scheduled_tasks[pipeline_id] = task

        return {
            "status": "scheduled",
            "pipeline_id": pipeline_id,
            "cron": cron,
            "interval_seconds": interval,
        }

    def _unschedule_pipeline(self, input_data: Any) -> Dict:
        pipeline_id = input_data if isinstance(input_data, str) else input_data.get("pipeline_id", "")
        if pipeline_id in self._scheduled_tasks:
            self._scheduled_tasks[pipeline_id].cancel()
            del self._scheduled_tasks[pipeline_id]
        if pipeline_id in self._pipelines:
            del self._pipelines[pipeline_id]
        return {"status": "unscheduled", "pipeline_id": pipeline_id}

    async def _scheduler_loop(self, pipeline_id: str, cron: Optional[str], interval: Optional[int]):
        """Simple scheduler loop. Supports interval_seconds or basic cron (minute-level)."""
        try:
            while True:
                await self._run_pipeline(self._pipelines.get(pipeline_id, {}), {})
                if interval:
                    await asyncio.sleep(interval)
                elif cron:
                    # Basic cron: "*/5 * * * *" = every 5 minutes
                    # For simplicity, parse minute-level cron
                    wait = self._cron_next_wait(cron)
                    await asyncio.sleep(wait)
                else:
                    break
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("workflow: scheduler loop crashed")

    def _cron_next_wait(self, cron: str) -> int:
        """Basic cron parser — supports */N * * * * format only."""
        try:
            parts = cron.split()
            if len(parts) >= 1 and parts[0].startswith("*/"):
                minutes = int(parts[0][2:])
                return minutes * 60
        except Exception:
            logger.exception("workflow: failed to parse cron expression %r", cron)
        return 300  # Default 5 minutes

    # ── Queries ────────────────────────────────────────────────────────────────

    def _list_pipelines(self) -> Dict:
        return {
            "status": "success",
            "pipelines": [
                {
                    "pipeline_id": pid,
                    "step_count": len(p.get("steps", [])),
                    "scheduled": pid in self._scheduled_tasks,
                }
                for pid, p in self._pipelines.items()
            ],
        }

    def _get_pipeline(self, input_data: Any) -> Dict:
        pipeline_id = input_data if isinstance(input_data, str) else input_data.get("pipeline_id", "")
        p = self._pipelines.get(pipeline_id)
        if not p:
            return {"status": "error", "error": f"Pipeline '{pipeline_id}' not found"}
        return {"status": "success", "pipeline": p}

    def _get_history(self) -> Dict:
        return {
            "status": "success",
            "runs": self._execution_history[-20:],  # Last 20
        }

    # ── Variable Interpolation ─────────────────────────────────────────────────

    def _interpolate(self, obj: Any, context: Dict) -> Any:
        """Replace {{steps.step_id.path}} with actual values from context."""
        if isinstance(obj, str):
            pattern = r"\{\{\s*([\w.\[\]]+)\s*\}\}"

            def replacer(match):
                path = match.group(1)
                return str(self._resolve_path(path, context))

            return re.sub(pattern, replacer, obj)
        elif isinstance(obj, dict):
            return {k: self._interpolate(v, context) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._interpolate(item, context) for item in obj]
        return obj

    def _resolve_path(self, path: str, context: Dict) -> Any:
        """Resolve dotted path like steps.design.result.text"""
        parts = path.split(".")
        current = context
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part, "")
            else:
                return ""
        return current if current is not None else ""

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _normalize_definition(self, input_data: Any) -> Dict:
        if isinstance(input_data, dict):
            return input_data
        if isinstance(input_data, str):
            try:
                return json.loads(input_data)
            except json.JSONDecodeError:
                return {"pipeline_id": None, "steps": []}
        return {"pipeline_id": None, "steps": []}
