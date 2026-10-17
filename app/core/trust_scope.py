"""Trust-scope enforcement for the live block-execution path.

The action-contract kernel (``app.blocks.core.action_contract``) defines the
reserved trust-scope keys and strips them from model-supplied arguments — but
until now it only ran inside generated products. This module wires the same
contract into ``/v1/execute``: caller-supplied identity/permission scope never
reaches a block, and the server-derived scope (from the validated API key)
always does.

At this surface three of the kernel's reserved keys are content-level, not
scope: ``domain`` (a search/filter facet, e.g. construction_advisor),
``context`` (conversational content, e.g. chat) and ``project_id`` (a
workspace selector pending the trial-boundary work). They stay caller-visible;
everything identity- or permission-bearing is server-controlled.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from app.blocks.core.action_contract.models import RESERVED_CONTEXT_KEYS

# Content-level at the block API surface — see module docstring.
CONTENT_LEVEL_KEYS = frozenset({"domain", "context", "project_id"})

# ``_namespace`` selects WHOSE stored data a stateful block (memory, cache)
# reads or writes — that is trust scope, not content. It is always
# server-derived so one tenant can never name another's namespace.
ENFORCED_SCOPE_KEYS = frozenset((RESERVED_CONTEXT_KEYS - CONTENT_LEVEL_KEYS) | {"_namespace"})


def server_scope(auth: Dict[str, Any]) -> Dict[str, Any]:
    """Trust scope derived from the validated API key — the only authority."""
    key_id = str(auth.get("id") or "anonymous")
    tenant_id = f"apikey:{key_id}"
    return {
        "tenant_id": tenant_id,
        "user_id": str(auth.get("email") or key_id),
        # Stateful blocks (memory, cache) key their storage on this; it is
        # never caller-controllable, so tenants cannot cross namespaces.
        "_namespace": f"tenant:{tenant_id}",
    }


def _strip(mapping: Dict[str, Any]) -> Tuple[Dict[str, Any], list]:
    clean: Dict[str, Any] = {}
    warnings = []
    for key, value in mapping.items():
        if key in ENFORCED_SCOPE_KEYS:
            warnings.append(
                f"ignored caller-supplied '{key}' (trust scope is server-controlled)"
            )
            continue
        clean[key] = value
    return clean, warnings


def enforce_trust_scope(
    input_data: Any,
    params: Optional[Dict[str, Any]],
    auth: Dict[str, Any],
) -> Tuple[Any, Dict[str, Any], list]:
    """Return (input, params, warnings) with scope enforced.

    Reserved scope keys are stripped from caller input/params and replaced by
    the server-derived scope so blocks that read ``tenant_id``/``user_id``
    get the platform's truth, never the caller's claim.
    """
    scope = server_scope(auth)
    warnings: list = []

    clean_params, w = _strip(dict(params or {}))
    warnings.extend(w)
    clean_params.update(scope)

    clean_input = input_data
    if isinstance(input_data, dict):
        clean_input, w = _strip(dict(input_data))
        warnings.extend(w)
        clean_input.update(scope)

    return clean_input, clean_params, warnings
