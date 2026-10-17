"""Trust-scope enforcement on the live /v1/execute path.

Caller-supplied identity/permission scope must never reach a block; the
server-derived scope (from the validated API key) must.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.routers.execute import ExecuteRequest, _run_block


class _CaptureBlock:
    """Echo block: returns exactly what reached it."""

    def __init__(self):
        self.seen = None

    async def execute(self, input_data, params):
        self.seen = {"input": input_data, "params": params}
        return {
            "block": "capture",
            "request_id": "t",
            "status": "success",
            "result": {"input": input_data, "params": params},
            "confidence": 1.0,
            "source_id": "capture-t",
            "metadata": {},
            "processing_time_ms": 0,
        }


AUTH = {"id": "key-123", "email": "trial@example.com", "tier": "pro"}


def _patched(capture):
    return [
        patch("app.routers.execute.BLOCK_REGISTRY", {"capture": object}),
        patch("app.routers.execute.get_block_instance", lambda name: capture),
        patch("app.routers.execute.enforce_block_access", lambda name, auth: None),
        patch("app.routers.execute.adapt_input", lambda data, block: data),
    ]


@pytest.mark.asyncio
async def test_caller_supplied_scope_is_stripped_and_server_scope_injected():
    capture = _CaptureBlock()
    patches = _patched(capture)
    for p in patches:
        p.start()
    try:
        request = ExecuteRequest(
            block="capture",
            input={
                "text": "hello",
                "tenant_id": "someone-elses-tenant",
                "user_id": "admin",
                "permissions": ["*"],
                "knowledge_layer": 1,
                "corpus_id": "their-corpus",
            },
            params={
                "tenant_id": "someone-elses-tenant",
                "allowed_domains": ["*"],
                "top_k": 3,
            },
        )
        response = await _run_block(request, AUTH)
    finally:
        for p in patches:
            p.stop()

    seen_input = capture.seen["input"]
    seen_params = capture.seen["params"]

    # Caller scope never reaches the block.
    assert seen_input.get("tenant_id") != "someone-elses-tenant"
    assert seen_params.get("tenant_id") != "someone-elses-tenant"
    assert "permissions" not in seen_input
    assert "allowed_domains" not in seen_params
    assert "knowledge_layer" not in seen_input
    assert "corpus_id" not in seen_input

    # Server-derived scope does.
    assert seen_input["tenant_id"] == "apikey:key-123"
    assert seen_params["tenant_id"] == "apikey:key-123"
    assert seen_params["user_id"] == "trial@example.com"

    # Content-level fields survive untouched.
    assert seen_input["text"] == "hello"
    assert seen_params["top_k"] == 3

    # The response discloses what was stripped.
    warnings = str(response.get("metadata", {}))
    assert "tenant_id" in warnings


@pytest.mark.asyncio
async def test_non_dict_input_passes_through_with_scoped_params():
    capture = _CaptureBlock()
    patches = _patched(capture)
    for p in patches:
        p.start()
    try:
        request = ExecuteRequest(block="capture", input="plain text", params={})
        await _run_block(request, AUTH)
    finally:
        for p in patches:
            p.stop()

    assert capture.seen["input"] == "plain text"
    assert capture.seen["params"]["tenant_id"] == "apikey:key-123"
