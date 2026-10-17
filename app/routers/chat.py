import asyncio
import json
from typing import Any, AsyncIterator, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.blocks import BLOCK_REGISTRY
from app.dependencies import require_api_key
from app.dependencies import block_instances

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    model: str = "kimi-k2-0905-preview"
    stream: bool = False


SSE_MEDIA_TYPE = "text/event-stream"
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

VALID_ENVELOPE_TYPES = {
    "route", "start", "token", "tool_call", "tool_result",
    "sources", "heartbeat", "end", "error",
}


def _sse_event(payload: dict[str, Any]) -> str:
    """Serialize a canonical envelope event to an SSE data line."""
    return f"data: {json.dumps(payload)}\n\n"


async def _canonical_stream(
    stream_gen: AsyncIterator[Any],
    *,
    session_id: Optional[str] = None,
    heartbeat_interval: float = 5.0,
) -> AsyncIterator[str]:
    """Convert a block's stream into the canonical SSE envelope.

    Emits:
      - start (first)
      - token / tool_call / tool_result / sources / heartbeat (zero or more)
      - exactly one end or error (last)

    The block may yield either raw content strings or dicts with a ``type``
    field. Raw strings become ``token`` events. Dicts with a recognized type
    pass through; unrecognized dicts are serialized as-is. Heartbeats are
    emitted when no event arrives for ``heartbeat_interval`` seconds during
    long tool waits.
    """
    yield _sse_event({"type": "start", "session_id": session_id})

    last_activity = asyncio.get_event_loop().time()
    ended = False

    try:
        while True:
            timeout = heartbeat_interval - (asyncio.get_event_loop().time() - last_activity)
            try:
                item = await asyncio.wait_for(stream_gen.__anext__(), timeout=max(timeout, 0.01))
            except asyncio.TimeoutError:
                now = asyncio.get_event_loop().time()
                if now - last_activity >= heartbeat_interval:
                    yield _sse_event({"type": "heartbeat"})
                    last_activity = now
                continue

            last_activity = asyncio.get_event_loop().time()

            if isinstance(item, dict):
                etype = item.get("type")
                if etype in VALID_ENVELOPE_TYPES:
                    if etype in ("end", "error"):
                        ended = True
                    yield _sse_event(item)
                    if ended:
                        return
                else:
                    # Pass through unknown dicts defensively.
                    yield _sse_event(item)
            elif isinstance(item, str):
                # Support legacy JSON-encoded error strings emitted by ChatBlock.
                if item.startswith('{"type":'):
                    try:
                        payload = json.loads(item)
                        if payload.get("type") in VALID_ENVELOPE_TYPES:
                            if payload["type"] in ("end", "error"):
                                ended = True
                            yield _sse_event(payload)
                            if ended:
                                return
                            continue
                    except json.JSONDecodeError:
                        pass
                yield _sse_event({"type": "token", "content": item})
            else:
                yield _sse_event({"type": "token", "content": str(item)})

    except StopAsyncIteration:
        pass
    except Exception as e:
        yield _sse_event({"type": "error", "message": str(e)})
        return

    if not ended:
        yield _sse_event({"type": "end", "complete": True})


@router.post("/chat")
async def chat(request: ChatRequest, auth: dict = Depends(require_api_key)):
    """Primary chat endpoint — consumed by the SPA's `api.sendMessage`.

    The other chat-shaped routes in this file (`/chat/stream`,
    `/v1/chat`, `/v1/chat/stream`) exist for streaming/MCP use cases but
    are NOT consumed by the current SPA. Don't delete them without
    auditing external callers, but treat them as legacy until the SPA
    grows a streaming UI.
    """
    if "chat" not in BLOCK_REGISTRY:
        raise HTTPException(500, "Chat block not available")

    try:
        if "chat" not in block_instances:
            block_instances["chat"] = BLOCK_REGISTRY["chat"]()

        block = block_instances["chat"]
        result = await block.execute(request.message, {
            "model": request.model,
            "stream": False,
        })

        # Pass through fields the SPA needs: fallback flag (so the user gets a
        # "credits exhausted" warning instead of mistaking offline rule-based
        # output for a real LLM response), provider, and model.
        inner = result.get("result", {}) if isinstance(result, dict) else {}
        return {
            "text": inner.get("text", ""),
            "model": inner.get("model") or request.model,
            "provider": inner.get("provider"),
            "fallback": inner.get("fallback", False),
            "fallback_reason": inner.get("fallback_reason"),
        }

    except Exception as e:
        raise HTTPException(500, f"Chat failed: {str(e)}")


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest, auth: dict = Depends(require_api_key)):
    """Streaming chat endpoint using the canonical SSE envelope."""
    if "chat" not in BLOCK_REGISTRY:
        raise HTTPException(500, "Chat block not available")

    async def event_stream():
        if "chat" not in block_instances:
            block_instances["chat"] = BLOCK_REGISTRY["chat"]()

        block = block_instances["chat"]
        result = await block.execute(request.message, {
            "model": request.model,
            "stream": True,
        })

        stream_gen = result.get("result", {}).get("stream")
        if stream_gen is None:
            # Fallback: simulate streaming from complete text.
            text = result.get("result", {}).get("text", "")
            words = text.split()

            async def _fallback_gen():
                for word in words:
                    yield word + " "
                    await asyncio.sleep(0.05)

            stream_gen = _fallback_gen()

        async for event in _canonical_stream(stream_gen):
            yield event

    return StreamingResponse(
        event_stream(),
        media_type=SSE_MEDIA_TYPE,
        headers=SSE_HEADERS,
    )


@router.post("/v1/chat")
async def chat_v1(request: ChatRequest, auth: dict = Depends(require_api_key)):
    """Simple chat endpoint (v1 API)."""
    return await chat(request)


@router.post("/v1/chat/stream")
async def chat_stream_v1(request: Request, auth: dict = Depends(require_api_key)):
    """Streaming chat endpoint (v1 API) with flexible JSON body."""
    if "chat" not in BLOCK_REGISTRY:
        raise HTTPException(500, "Chat block not available")

    try:
        body = await request.json()
    except Exception:
        body = {}

    prompt = body.get("prompt", body.get("message", ""))
    model = body.get("model", body.get("provider", "kimi-k2-0905-preview"))
    session_id = body.get("session_id", "default")
    history = body.get("history", [])

    async def event_stream():
        if "chat" not in block_instances:
            block_instances["chat"] = BLOCK_REGISTRY["chat"]()

        block = block_instances["chat"]
        result = await block.execute(
            {"text": prompt, "history": history} if history else prompt,
            {"model": model, "stream": True}
        )

        stream_gen = result.get("result", {}).get("stream")
        if stream_gen is None:
            text = result.get("result", {}).get("text", "")

            async def _fallback_gen():
                for word in text.split():
                    yield word + " "
                    await asyncio.sleep(0.05)

            stream_gen = _fallback_gen()

        async for event in _canonical_stream(stream_gen, session_id=session_id):
            yield event

    return StreamingResponse(
        event_stream(),
        media_type=SSE_MEDIA_TYPE,
        headers=SSE_HEADERS,
    )
