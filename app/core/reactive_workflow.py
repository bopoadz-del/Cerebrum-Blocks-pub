"""Reactive workflow engine — auto-chain blocks on connector events."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field
from app.core.http_errors import error_kind

logger = logging.getLogger(__name__)

_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


class WorkflowStep(BaseModel):
    block_id: str
    params: Dict[str, Any] = Field(default_factory=dict)
    input_mapping: Dict[str, str] = Field(default_factory=dict)


class WorkflowDefinition(BaseModel):
    workflow_id: str
    trigger_event_type: str
    min_severity: Optional[str] = None
    steps: List[WorkflowStep] = Field(default_factory=list)
    enabled: bool = True
    description: str = ""


class WorkflowTriggerRegistration(BaseModel):
    trigger_id: str = Field(default_factory=lambda: str(uuid4())[:12])
    event_type: str
    min_severity: Optional[str] = None
    steps: List[WorkflowStep] = Field(default_factory=list)
    enabled: bool = True
    description: str = ""


def _default_video_anomaly_trigger() -> WorkflowTriggerRegistration:
    channel = os.getenv("VIDEO_ANOMALY_NOTIFY_CHANNEL", "webhook")
    return WorkflowTriggerRegistration(
        trigger_id="builtin-video-anomaly",
        event_type="video.anomaly",
        min_severity=os.getenv("VIDEO_ANOMALY_MIN_SEVERITY", "medium"),
        description="Default: video anomaly → notification",
        steps=[
            WorkflowStep(
                block_id="notification",
                params={"action": "send"},
                input_mapping={
                    "channel": "context.notify_channel",
                    "message": "context.message",
                    "to": "context.notify_to",
                    "url": "context.notify_to",
                    "payload": "context.workflow_payload",
                },
            ),
        ],
    )


def _resolve_mapping(path: str, context: Dict[str, Any]) -> Any:
    parts = path.split(".")
    cur: Any = context
    for part in parts:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _build_step_input(step: WorkflowStep, context: Dict[str, Any]) -> Dict[str, Any]:
    if not step.input_mapping:
        return dict(context.get("input") or context)
    result: Dict[str, Any] = {}
    for target_key, source_path in step.input_mapping.items():
        value = _resolve_mapping(source_path, context)
        if value is not None:
            result[target_key] = value
    return result


class ReactiveWorkflowEngine:
    """Match connector events to registered triggers and execute step chains."""

    def __init__(self) -> None:
        self._triggers: Dict[str, WorkflowTriggerRegistration] = {}
        self._register_builtin_triggers()

    def _register_builtin_triggers(self) -> None:
        builtin = _default_video_anomaly_trigger()
        self._triggers[builtin.trigger_id] = builtin

    def register_trigger(self, registration: WorkflowTriggerRegistration) -> WorkflowTriggerRegistration:
        self._triggers[registration.trigger_id] = registration
        return registration

    def unregister_trigger(self, trigger_id: str) -> bool:
        if trigger_id == "builtin-video-anomaly":
            return False
        return self._triggers.pop(trigger_id, None) is not None

    def list_triggers(self) -> List[Dict[str, Any]]:
        return [t.model_dump(mode="json") for t in self._triggers.values()]

    def _matches_severity(self, trigger: WorkflowTriggerRegistration, context: Dict[str, Any]) -> bool:
        min_sev = trigger.min_severity
        if not min_sev:
            return True
        min_rank = _SEVERITY_RANK.get(str(min_sev).lower(), 1)
        anomalies = context.get("anomalies") or []
        if not anomalies:
            return False
        for anomaly in anomalies:
            if not isinstance(anomaly, dict):
                continue
            sev = anomaly.get("severity", "medium")
            if hasattr(sev, "value"):
                sev = sev.value
            if _SEVERITY_RANK.get(str(sev).lower(), 0) >= min_rank:
                return True
        return False

    def _matching_triggers(self, event_type: str, context: Dict[str, Any]) -> List[WorkflowTriggerRegistration]:
        matches: List[WorkflowTriggerRegistration] = []
        for trigger in self._triggers.values():
            if not trigger.enabled:
                continue
            if trigger.event_type != event_type:
                continue
            if not self._matches_severity(trigger, context):
                continue
            matches.append(trigger)
        return matches

    async def _execute_block(self, block_id: str, input_data: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        from app.dependencies import get_block_instance

        block = get_block_instance(block_id)
        if hasattr(block, "process"):
            result = await block.process(input_data, params)
        elif hasattr(block, "execute"):
            result = await block.execute(input_data, params)
        else:
            raise RuntimeError(f"Block '{block_id}' has no process/execute method")
        return result if isinstance(result, dict) else {"result": result}

    async def execute_workflow(
        self,
        trigger: WorkflowTriggerRegistration,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        step_results: List[Dict[str, Any]] = []
        for i, step in enumerate(trigger.steps):
            step_input = _build_step_input(step, context)
            try:
                result = await self._execute_block(step.block_id, step_input, step.params)
                step_results.append({
                    "step": i,
                    "block_id": step.block_id,
                    "status": "success",
                    "result": result,
                })
                context.setdefault("step_results", []).append(result)
            except Exception as exc:
                logger.exception("reactive workflow step %s (%s) failed: %s", i, step.block_id, exc)
                step_results.append({
                    "step": i,
                    "block_id": step.block_id,
                    "status": "error",
                    "error": str(exc), "error_kind": error_kind(exc),
                })
                break
        return {
            "workflow_id": trigger.trigger_id,
            "event_type": trigger.event_type,
            "triggered": True,
            "steps_executed": len(step_results),
            "step_results": step_results,
        }

    async def dispatch_event(
        self,
        event_type: str,
        context: Dict[str, Any],
        *,
        background: bool = True,
    ) -> List[Dict[str, Any]]:
        """Match triggers for event_type and execute workflows."""
        triggers = self._matching_triggers(event_type, context)
        if not triggers:
            return []

        results: List[Dict[str, Any]] = []
        for trigger in triggers:
            if background:
                task = asyncio.create_task(self.execute_workflow(trigger, dict(context)))
                results.append({
                    "trigger_id": trigger.trigger_id,
                    "event_type": event_type,
                    "status": "scheduled",
                    "task": task,
                })
            else:
                result = await self.execute_workflow(trigger, context)
                results.append(result)
        return results

    async def dispatch_video_anomaly(
        self,
        metadata: Dict[str, Any],
        anomalies: List[Dict[str, Any]],
        *,
        notify_channel: Optional[str] = None,
        notify_to: Optional[str] = None,
        message: Optional[str] = None,
        auto_trigger: bool = True,
        background: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Convenience entry for video ingest anomaly auto-chaining."""
        if not auto_trigger or not anomalies:
            return None

        camera_id = metadata.get("camera_id", "unknown")
        types = ", ".join({a.get("anomaly_type", "unknown") for a in anomalies if isinstance(a, dict)})
        default_message = message or (
            f"Video anomaly alert — camera={camera_id}, count={len(anomalies)}, types=[{types}]"
        )
        channel = notify_channel or os.getenv("VIDEO_ANOMALY_NOTIFY_CHANNEL", "webhook")

        context = {
            "input": metadata,
            "metadata": metadata,
            "anomalies": anomalies,
            "camera_id": camera_id,
            "notify_channel": channel,
            "notify_to": notify_to,
            "message": default_message,
            "workflow_payload": {
                "trigger": "video_anomaly",
                "anomaly_count": len(anomalies),
                "anomalies": anomalies,
                "camera_id": camera_id,
                "channel": channel,
                "message": default_message,
            },
            "context": {
                "notify_channel": channel,
                "notify_to": notify_to,
                "message": default_message,
                "workflow_payload": {
                    "trigger": "video_anomaly",
                    "anomaly_count": len(anomalies),
                    "anomalies": anomalies,
                    "camera_id": camera_id,
                },
            },
        }

        results = await self.dispatch_event("video.anomaly", context, background=background)
        if not results:
            return None
        if background:
            return {"status": "scheduled", "triggers": len(results)}
        return results[0] if len(results) == 1 else {"status": "success", "workflows": results}


_engine: Optional[ReactiveWorkflowEngine] = None


def get_reactive_engine() -> ReactiveWorkflowEngine:
    global _engine
    if _engine is None:
        _engine = ReactiveWorkflowEngine()
    return _engine
