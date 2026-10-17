"""Video ingest router — POST /v1/video/ingest."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.http_errors import classify_block_error
from app.dependencies import get_block_instance, require_api_key

router = APIRouter(prefix="/v1/video", tags=["video"])


class ZoneOccupancyIn(BaseModel):
    zone_id: str
    label: Optional[str] = None
    count: int = 0
    capacity: Optional[int] = None
    occupancy_pct: Optional[float] = None


class QueueInfoIn(BaseModel):
    queue_id: str
    label: Optional[str] = None
    length: int = 0
    avg_wait_seconds: Optional[float] = None
    threshold_exceeded: bool = False


class AnomalyIn(BaseModel):
    anomaly_type: str
    severity: str = "medium"
    zone_id: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    description: Optional[str] = None


class VideoIngestRequest(BaseModel):
    source_id: str = "api"
    camera_id: str
    frame_id: Optional[str] = None
    zones: List[ZoneOccupancyIn] = Field(default_factory=list)
    queues: List[QueueInfoIn] = Field(default_factory=list)
    anomalies: List[AnomalyIn] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    raw_metadata: Dict[str, Any] = Field(default_factory=dict)
    auto_trigger: bool = True
    notify_channel: Optional[str] = None
    notify_to: Optional[str] = None


@router.post("/ingest")
async def video_ingest(
    request: VideoIngestRequest,
    auth: dict = Depends(require_api_key),
):
    """Ingest video analytics metadata; optionally chain anomaly trigger."""
    ingest = get_block_instance("video_metadata_ingest")
    payload = request.model_dump()
    result = await ingest.process(payload, {"action": "ingest"})

    if result.get("status") == "error":
        err = result.get("error", "Ingest failed")
        raise HTTPException(status_code=classify_block_error(result), detail=err)

    # Reactive engine runs inside video_metadata_ingest when auto_trigger=true.
    # Legacy manual chaining via video_anomaly_trigger remains available via /execute.
    if not result.get("workflow") and result.get("trigger_recommended") and request.auto_trigger:
        from app.core.reactive_workflow import get_reactive_engine

        workflow_result = await get_reactive_engine().dispatch_video_anomaly(
            payload,
            result.get("anomalies", []),
            notify_channel=request.notify_channel,
            notify_to=request.notify_to,
            auto_trigger=True,
            background=False,
        )
        if workflow_result:
            result["workflow"] = workflow_result

    return result
