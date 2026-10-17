"""LLM provider selection — Kimi (Moonshot) only, the platform's single provider."""

from __future__ import annotations

import os
from typing import Dict

KIMI_BASE_URL = "https://api.moonshot.ai/v1"
KIMI_DEFAULT_MODEL = "kimi-k2-0905-preview"


def _llm_config() -> Dict[str, str]:
    """Return the Kimi (Moonshot) provider config.

    Kimi is the platform's only LLM provider; its cloud API is OpenAI-compatible.
    Configure the key with ``KIMI_API_KEY`` (or ``MOONSHOT_API_KEY``); override
    the endpoint/model with ``KIMI_BASE_URL`` / ``KIMI_MODEL`` if needed.

    Keeps the historical return shape (``provider``/``url``/``env_key``/
    ``default_model``) so existing callers need no change.
    """
    base = os.getenv("KIMI_BASE_URL", os.getenv("MOONSHOT_BASE_URL", KIMI_BASE_URL)).rstrip("/")
    if base.endswith("/chat/completions"):
        url = base
    elif base.endswith("/v1"):
        url = base + "/chat/completions"
    else:
        url = base + "/v1/chat/completions"

    env_key = "KIMI_API_KEY" if os.getenv("KIMI_API_KEY") else "MOONSHOT_API_KEY"
    return {
        "provider": "kimi",
        "url": url,
        "env_key": env_key,
        "default_model": os.getenv("KIMI_MODEL", os.getenv("MOONSHOT_MODEL", KIMI_DEFAULT_MODEL)),
    }
