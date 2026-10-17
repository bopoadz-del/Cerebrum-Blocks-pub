"""Tinker sampling client for the posture checkpoint.

The private <private-repo> tree at 4e167a7 was not readable from this
checkout, so this module is the Store-side client of the hook contract
named in ``docs/serve/FORK_INTEGRATION.md`` at that commit:

* ``sample_posture(user_text, fork_context=..., allowed_formula_ids=...)``
* refuse when ``fork_context`` is not attached (``None``)
* do not retrieve, and do not apply probe ids or domain word lists

Sampling uses Tinker's documented OpenAI-compatible completions endpoint.
The model name is the checkpoint URI in ``configs/serve/posture-epoch2.json``.
``TINKER_API_KEY`` is read from the environment at call time.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

# Documented Tinker OpenAI-compatible base. The checkpoint path is the model.
# https://tinker-docs.thinkingmachines.ai/tinker/compatible-apis/openai/
TINKER_COMPLETIONS_URL = (
    "https://tinker.thinkingmachines.dev/services/tinker-prod/oai/api/v1/completions"
)

_SERVE_CONFIG = (
    Path(__file__).resolve().parents[1] / "configs" / "serve" / "posture-epoch2.json"
)

CHECKPOINT_URI = (
    "tinker://d33e27e4-5533-5af4-9039-c9bf8254d4b7:train:0/"
    "sampler_weights/posture-qwen3-8b-lora-r16-epoch2"
)


class ContextMissing(Exception):
    """``fork_context`` was not attached. Callers must refuse, not answer."""


class PostureSampleError(Exception):
    """The sampler did not return an answer. Never a fabricated one."""


def load_serve_config() -> dict:
    """The pinned serve file. The checkpoint URI is the only sampling input."""
    try:
        data = json.loads(_SERVE_CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PostureSampleError(f"serve config unreadable: {exc}") from exc
    if not isinstance(data, dict):
        raise PostureSampleError("serve config is not an object")
    checkpoint = data.get("checkpoint")
    if checkpoint != CHECKPOINT_URI:
        raise PostureSampleError("serve config checkpoint does not match the pin")
    return data


def _prompt(user_text: str, fork_context: Any, allowed_formula_ids: Any) -> str:
    """Serialize the hook arguments. No retrieval and no domain vocabulary."""
    body: dict[str, Any] = {
        "fork_context": fork_context,
        "user_text": user_text,
    }
    if allowed_formula_ids is not None:
        body["allowed_formula_ids"] = allowed_formula_ids
    try:
        return json.dumps(body, ensure_ascii=False, sort_keys=True)
    except TypeError as exc:
        raise PostureSampleError("fork_context is not JSON-serializable") from exc


def _completion_text(body: Mapping[str, Any]) -> str:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise PostureSampleError("sampler response has no choices")
    first = choices[0]
    if not isinstance(first, dict) or "text" not in first:
        raise PostureSampleError("sampler response has no completion text")
    text = first["text"]
    if not isinstance(text, str):
        raise PostureSampleError("sampler completion text is not a string")
    return text


def _default_post(url: str, payload: Mapping[str, Any], api_key: str) -> dict:
    import httpx

    try:
        response = httpx.post(
            url,
            json=dict(payload),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=60.0,
        )
        response.raise_for_status()
        parsed = response.json()
    except httpx.HTTPError as exc:
        raise PostureSampleError(f"tinker sampling failed: {exc}") from exc
    if not isinstance(parsed, dict):
        raise PostureSampleError("tinker sampling response is not an object")
    return parsed


def sample_posture(
    user_text: str,
    fork_context: Any = None,
    allowed_formula_ids: Any = None,
    *,
    post: Optional[Callable[..., dict]] = None,
) -> dict:
    """Sample the pinned posture checkpoint.

    Refuses before any network call when ``fork_context`` is ``None``.
    ``allowed_formula_ids`` is forwarded as the caller attached it; this
    function does not interpret formula ids.
    """
    if fork_context is None:
        raise ContextMissing("fork_context is not attached")
    if not isinstance(user_text, str) or not user_text.strip():
        raise PostureSampleError("user_text is required")

    checkpoint = load_serve_config()["checkpoint"]
    api_key = os.environ.get("TINKER_API_KEY")
    if not api_key:
        raise PostureSampleError("TINKER_API_KEY is not set")

    payload = {
        "model": checkpoint,
        "prompt": _prompt(user_text, fork_context, allowed_formula_ids),
    }
    sender = post or _default_post
    body = sender(TINKER_COMPLETIONS_URL, payload, api_key)
    if not isinstance(body, dict):
        raise PostureSampleError("tinker sampling response is not an object")
    return {
        "checkpoint": checkpoint,
        "text": _completion_text(body),
    }
