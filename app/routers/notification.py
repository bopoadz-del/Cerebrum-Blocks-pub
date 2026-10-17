"""Notification Router — Unified messaging endpoints."""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.dependencies import require_api_key, get_block_instance

router = APIRouter()


class SendRequest(BaseModel):
    channel: str = Field(..., description="email | webhook | slack | mcp")
    to: Optional[str] = Field(default=None, description="Recipient (email address or URL)")
    message: str = Field(default="", description="Message text or payload")
    subject: Optional[str] = Field(default=None, description="Email subject")
    html: Optional[str] = Field(default=None, description="HTML body for email")
    url: Optional[str] = Field(default=None, description="Webhook URL override")
    headers: Optional[Dict] = Field(default=None, description="Custom headers for webhook")
    payload: Optional[Any] = Field(default=None, description="Webhook payload")
    blocks: Optional[List[Dict]] = Field(default=None, description="Slack block kit")


class BroadcastRequest(BaseModel):
    channels: List[str] = Field(..., description="any of email | webhook | slack | mcp")
    to: Optional[str] = Field(default=None)
    message: str = Field(default="")
    subject: Optional[str] = Field(default=None)
    html: Optional[str] = Field(default=None)


@router.post("/notify/send")
async def notify_send(request: SendRequest, auth: dict = Depends(require_api_key)):
    """Send a notification via any channel."""
    block = get_block_instance("notification")
    result = await block.process(request.model_dump(), {"action": "send"})

    if result.get("status") == "error":
        from app.core.http_errors import classify_block_error
        err = result.get("error", "Send failed")
        raise HTTPException(status_code=classify_block_error(result), detail=err)

    return result.get("result", result)


@router.post("/notify/broadcast")
async def notify_broadcast(request: BroadcastRequest, auth: dict = Depends(require_api_key)):
    """Broadcast to multiple channels simultaneously."""
    block = get_block_instance("notification")
    result = await block.process(request.model_dump(), {"action": "broadcast"})
    return result.get("result", result)


@router.get("/notify/health")
async def notify_health(auth: dict = Depends(require_api_key)):
    """Check which notification channels are configured."""
    block = get_block_instance("notification")
    result = await block.process(None, {"action": "health"})
    return result.get("result", result)
