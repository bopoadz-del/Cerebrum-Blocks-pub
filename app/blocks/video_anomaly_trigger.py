"""Video anomaly trigger — react to anomalies and dispatch notifications or workflow payloads."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.connector_events import Anomaly, VideoMetadata
from app.core.universal_base import UniversalBlock
from app.core.video_store import get_video_store
from app.core.http_errors import error_kind


class VideoAnomalyTriggerBlock(UniversalBlock):
    name = "video_anomaly_trigger"
    version = "1.0.0"
    description = "Watch video metadata for anomalies and chain to notification or workflow triggers"
    layer = 2
    tags = ["connector", "video", "trigger", "anomaly", "reactive"]
    requires: List[str] = ["notification"]

    default_config = {
        "default_channel": "webhook",
        "min_severity": "medium",
        "notify_on_types": [],
    }

    _SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}

    ui_schema = {
        "input": {
            "type": "json",
            "placeholder": '{"metadata": {...}} or {"event_id": "..."}',
            "multiline": True,
        },
        "output": {
            "type": "json",
            "fields": [
                {"name": "triggered", "type": "boolean", "label": "Triggered"},
                {"name": "anomalies", "type": "json", "label": "Anomalies"},
                {"name": "notification", "type": "json", "label": "Notification Result"},
            ],
        },
        "params": [
            {
                "name": "action",
                "type": "select",
                "label": "Action",
                "options": ["evaluate", "scan_store", "health"],
                "default": "evaluate",
            },
            {
                "name": "channel",
                "type": "select",
                "label": "Notify Channel",
                "options": ["webhook", "email", "slack"],
                "default": "webhook",
            },
            {
                "name": "send_notification",
                "type": "select",
                "label": "Send Notification",
                "options": ["true", "false"],
                "default": "true",
            },
        ],
        "quick_actions": [
            {"icon": "🚨", "label": "Evaluate anomalies", "prompt": "Check metadata for anomalies"},
        ],
    }

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        data = input_data if isinstance(input_data, dict) else {}
        action = params.get("action") or data.get("action", "evaluate")

        if action == "health":
            return {"status": "healthy", "block": self.name, "version": self.version}

        if action == "scan_store":
            store = get_video_store()
            since = data.get("since")
            anomalies = await store.list_anomalies(limit=int(data.get("limit", 50)))
            qualifying = [a for a in anomalies if self._qualifies(a, params)]
            return await self._build_trigger_response(qualifying, params, data)

        return await self._evaluate(data, params)

    async def _evaluate(self, data: Dict, params: Dict) -> Dict:
        metadata_payload = data.get("metadata") or data
        try:
            metadata = VideoMetadata.model_validate(metadata_payload)
        except Exception as exc:
            return {"status": "error", "error": f"Invalid metadata: {exc}"}

        qualifying = [a for a in metadata.anomalies if self._qualifies(a, params)]
        return await self._build_trigger_response(qualifying, params, data, metadata=metadata)

    def _qualifies(self, anomaly: Anomaly, params: Dict) -> bool:
        min_sev = (
            params.get("min_severity")
            or self.config.get("min_severity")
            or "medium"
        )
        min_rank = self._SEVERITY_RANK.get(str(min_sev).lower(), 1)
        anomaly_rank = self._SEVERITY_RANK.get(
            str(anomaly.severity.value if hasattr(anomaly.severity, "value") else anomaly.severity).lower(),
            0,
        )
        if anomaly_rank < min_rank:
            return False

        allowed_types = params.get("notify_on_types") or self.config.get("notify_on_types") or []
        if allowed_types and anomaly.anomaly_type not in allowed_types:
            return False
        return True

    async def _build_trigger_response(
        self,
        anomalies: List[Anomaly],
        params: Dict,
        data: Dict,
        metadata: Optional[VideoMetadata] = None,
    ) -> Dict:
        if not anomalies:
            return {
                "status": "success",
                "triggered": False,
                "anomalies": [],
                "message": "No qualifying anomalies",
            }

        channel = (
            params.get("channel")
            or data.get("channel")
            or self.config.get("default_channel")
            or "webhook"
        )
        message = data.get("message") or self._format_message(anomalies, metadata)
        send = str(params.get("send_notification", data.get("send_notification", "true"))).lower() != "false"

        workflow_payload = {
            "trigger": "video_anomaly",
            "anomaly_count": len(anomalies),
            "anomalies": [a.model_dump(mode="json") for a in anomalies],
            "camera_id": metadata.camera_id if metadata else data.get("camera_id"),
            "channel": channel,
            "message": message,
        }

        notification_result = None
        if send:
            notification_result = await self._dispatch_notification(channel, message, data, workflow_payload)

        return {
            "status": "success",
            "triggered": True,
            "anomalies": [a.model_dump(mode="json") for a in anomalies],
            "workflow_payload": workflow_payload,
            "notification": notification_result,
        }

    def _format_message(
        self, anomalies: List[Anomaly], metadata: Optional[VideoMetadata] = None
    ) -> str:
        camera = metadata.camera_id if metadata else "unknown"
        types = ", ".join({a.anomaly_type for a in anomalies})
        return f"Video anomaly alert — camera={camera}, count={len(anomalies)}, types=[{types}]"

    async def _dispatch_notification(
        self, channel: str, message: str, data: Dict, workflow_payload: Dict
    ) -> Optional[Dict]:
        notif = self.get_dep("notification")
        if notif is None:
            from app.dependencies import get_block_instance

            try:
                notif = get_block_instance("notification")
            except Exception:
                return {"status": "skipped", "reason": "notification block unavailable"}

        payload = {
            "channel": channel,
            "message": message,
            "to": data.get("to") or data.get("url"),
            "url": data.get("url"),
            "payload": workflow_payload,
        }
        try:
            return await notif.process(payload, {"action": "send"})
        except Exception as exc:
            return {"status": "error", "error": str(exc), "error_kind": error_kind(exc)}
