"""Video metadata ingest block — validate and persist camera analytics events."""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import ValidationError

from app.core.connector_events import ConnectorEvent, VideoMetadata
from app.core.universal_base import UniversalBlock
from app.core.video_store import get_video_store


class VideoMetadataIngestBlock(UniversalBlock):
    name = "video_metadata_ingest"
    version = "1.0.0"
    description = "Validate video analytics metadata and persist to the video store"
    layer = 2
    tags = ["connector", "video", "ingest", "analytics"]
    requires: List[str] = []

    ui_schema = {
        "input": {
            "type": "json",
            "placeholder": '{"camera_id": "lobby-1", "zones": [], "anomalies": []}',
            "multiline": True,
        },
        "output": {
            "type": "json",
            "fields": [
                {"name": "event_id", "type": "text", "label": "Event ID"},
                {"name": "stored", "type": "boolean", "label": "Stored"},
                {"name": "anomaly_count", "type": "number", "label": "Anomalies"},
            ],
        },
        "params": [
            {
                "name": "action",
                "type": "select",
                "label": "Action",
                "options": ["ingest", "list", "health"],
                "default": "ingest",
            },
        ],
        "quick_actions": [
            {"icon": "📹", "label": "Ingest frame", "prompt": "Ingest video metadata"},
        ],
    }

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        data = input_data if isinstance(input_data, dict) else {}
        action = params.get("action") or data.get("action", "ingest")

        if action == "health":
            store = get_video_store()
            return {
                "status": "healthy",
                "block": self.name,
                "store": type(store).__name__,
            }

        if action == "list":
            camera_id = data.get("camera_id") or params.get("camera_id")
            if not camera_id:
                return {"status": "error", "error": "camera_id required for list"}
            store = get_video_store()
            events = await store.list_by_camera(camera_id, limit=int(data.get("limit", 50)))
            return {
                "status": "success",
                "camera_id": camera_id,
                "events": [e.model_dump(mode="json") for e in events],
                "count": len(events),
            }

        return await self._ingest(data)

    async def _ingest(self, data: Dict) -> Dict:
        payload = data.get("metadata") or data
        try:
            metadata = VideoMetadata.model_validate(payload)
        except ValidationError as exc:
            return {"status": "error", "error": "Invalid VideoMetadata", "details": exc.errors()}

        store = get_video_store()
        event_id = await store.store(metadata)

        connector_event = ConnectorEvent(
            source="video_metadata_ingest",
            event_type="video.metadata.ingested",
            payload=metadata.model_dump(mode="json"),
            normalized_data={"event_id": event_id, "camera_id": metadata.camera_id},
            tags=["video", "ingest"],
        )

        result: Dict = {
            "status": "success",
            "event_id": event_id,
            "stored": True,
            "camera_id": metadata.camera_id,
            "anomaly_count": len(metadata.anomalies),
            "connector_event": connector_event.model_dump(mode="json"),
        }

        if metadata.anomalies and data.get("auto_trigger", True):
            result["trigger_recommended"] = True
            result["anomalies"] = [a.model_dump(mode="json") for a in metadata.anomalies]
            from app.core.reactive_workflow import get_reactive_engine

            workflow_result = await get_reactive_engine().dispatch_video_anomaly(
                metadata.model_dump(mode="json"),
                result["anomalies"],
                notify_channel=data.get("notify_channel"),
                notify_to=data.get("notify_to") or data.get("url"),
                message=data.get("message"),
                auto_trigger=True,
                background=False,
            )
            if workflow_result:
                result["workflow"] = workflow_result

        return result
