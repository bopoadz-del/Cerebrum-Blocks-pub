"""Posture model — final-answer sampling for The Fork.

Thin Store wrapper around the <private-repo> posture client
(https://github.com/bopoadz-del/<private-repo> @ 4e167a7). Retrieval stays on
The Fork. This block does not retrieve. It calls ``sample_posture`` and
refuses when ``fork_context`` is missing or ``None``.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from app.core.universal_base import UniversalBlock
from app.vendor.cerebrum_slm.posture_model import (
    ContextMissing,
    PostureSampleError,
    sample_posture,
)


def _lookup(payload: Any, params: Optional[Dict[str, Any]], key: str) -> Tuple[bool, Any]:
    """Return (present, value) from the input payload, then from params."""
    if isinstance(payload, dict) and key in payload:
        return True, payload[key]
    if isinstance(params, dict) and key in params:
        return True, params[key]
    return False, None


def _user_text(input_data: Any, params: Optional[Dict[str, Any]]) -> Optional[str]:
    if isinstance(input_data, str):
        return input_data
    present, value = _lookup(input_data, params, "user_text")
    if present:
        return value if isinstance(value, str) else None
    if isinstance(input_data, dict):
        for key in ("text", "message"):
            candidate = input_data.get(key)
            if isinstance(candidate, str):
                return candidate
    return None


class PostureModelBlock(UniversalBlock):
    """Sample a final answer from the pinned posture checkpoint.

    ``fork_context`` must be attached by the caller. A missing or ``None``
    context is a refusal: this block does not retrieve one.
    """

    name = "posture_model"
    version = "1.0.0"
    description = (
        "Final-answer sampler pinned to <private-repo>@4e167a7. Calls "
        "sample_posture against the Tinker posture checkpoint "
        "(TINKER_API_KEY). Retrieval stays on The Fork: refuses when "
        "fork_context is not attached."
    )
    layer = 3
    tags = ["posture", "sampling", "tinker", "final-answer"]
    requires = ["fork_context"]
    author = "Cerebrum Team"

    default_config: Dict[str, Any] = {}

    ui_schema = {
        "input": {
            "type": "json",
            "placeholder": '{"user_text": "...", "fork_context": {}}',
            "multiline": True,
        },
        "output": {
            "type": "json",
            "fields": [
                {"name": "status", "type": "string", "label": "Status"},
                {"name": "answer", "type": "string", "label": "Answer"},
            ],
        },
    }

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        present, fork_context = _lookup(input_data, params, "fork_context")
        if not present or fork_context is None:
            return {
                "status": "refused",
                "answer": None,
                "error": "fork_context is not attached",
            }

        user_text = _user_text(input_data, params)
        _, allowed_formula_ids = _lookup(input_data, params, "allowed_formula_ids")
        try:
            sampled = sample_posture(
                user_text if isinstance(user_text, str) else "",
                fork_context=fork_context,
                allowed_formula_ids=allowed_formula_ids,
            )
        except ContextMissing:
            return {
                "status": "refused",
                "answer": None,
                "error": "fork_context is not attached",
            }
        except PostureSampleError as exc:
            return {
                "status": "failed",
                "answer": None,
                "error": str(exc),
            }
        return {
            "status": "ok",
            "answer": sampled["text"],
            "checkpoint": sampled["checkpoint"],
        }
