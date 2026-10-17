"""Finance & Investment Suite domain knowledge — CRITICAL_RULES and prompt helpers."""

from __future__ import annotations

CRITICAL_RULES: dict[str, str] = {
    # TODO: add non-negotiable domain rules, e.g. "never_diagnose": "..."
}


def get_system_prompt() -> str:
    """Return supplemental system prompt context from the knowledge base."""
    if not CRITICAL_RULES:
        return ""
    lines = ["Critical rules:"]
    for key, rule in CRITICAL_RULES.items():
        lines.append(f"- {key}: {rule}")
    return "\n".join(lines)
