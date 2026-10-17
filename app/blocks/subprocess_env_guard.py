"""Subprocess environment guard - the scrubbed environment The_Fork passes to
every subprocess it spawns, ported verbatim from The_Fork
``app/core/subprocess_env.py`` (security fix, audit Â§6.1).

The donor's incident: subprocesses spawned by the app - file converters
(ODAFileConverter, antiword), the code/bash sandbox block, hardware probes -
previously inherited the FULL parent environment, including SECRET_KEY,
DATABASE_URL (with the DB password), the LLM/provider API keys,
DATA_ENCRYPTION_KEY, cloud tokens, and the master key. The bash sandbox
could therefore ``echo $SECRET_KEY`` and exfiltrate it to output.

This block exposes the donor's denylist verbatim: exact secret names plus
substring patterns (case-insensitive). Denylist, not allowlist - deliberate:
a denylist can only ever REMOVE a variable that a working subprocess never
needed, so it cannot break a subprocess that was already working.

One fail-closed hardening beyond the donor's text: the donor applies
``extra`` last, so a caller-supplied extra could re-inject a secret-bearing
name. This block refuses such extras instead of letting them win - the
whole point of the fix is that a secret never reaches a subprocess.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from app.core.universal_base import UniversalBlock

# Exact secret names (belt). Connection strings that can carry credentials
# (DATABASE_URL, REDIS_URL) and named secrets that don't match a substring
# pattern (GDRIVE_SERVICE_ACCOUNT_JSON) are pinned here.
_FORBIDDEN_EXACT = frozenset({
    "SECRET_KEY",
    "DATABASE_URL",
    "REDIS_URL",
    "DATA_ENCRYPTION_KEY",
    "CEREBRUM_MASTER_KEY",
    "SENTRY_DSN",
    "GDRIVE_SERVICE_ACCOUNT_JSON",
    "BOOTSTRAP_USER_PASSWORD",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_ACCESS_TOKEN",
    "ONEDRIVE_ACCESS_TOKEN",
})

# Substring patterns (suspenders): any env var whose NAME contains one of these
# (case-insensitive) is treated as a secret and stripped. Covers *_API_KEY,
# *_TOKEN, *_SECRET, *_PASSWORD, R2_*ACCESS_KEY*, CEREBRUM_API_KEY_*,
# GITHUB_TOKEN, RENDER_API_KEY, service-account and signing keys, etc.
_FORBIDDEN_SUBSTRINGS = (
    "SECRET",
    "PASSWORD",
    "PASSWD",
    "CREDENTIAL",
    "PRIVATE_KEY",
    "API_KEY",
    "APIKEY",
    "ACCESS_KEY",
    "ACCESS_TOKEN",
    "REFRESH_TOKEN",
    "_TOKEN",
    "TOKEN_",
    "SERVICE_ACCOUNT",
    "_DSN",
    "MASTER_KEY",
    "SIGNING_KEY",
    "ENCRYPTION_KEY",
)


def is_secret_env_name(name: str) -> bool:
    """True if an env var NAME denotes a secret that must not reach a subprocess."""
    up = name.upper()
    if up in _FORBIDDEN_EXACT:
        return True
    return any(sub in up for sub in _FORBIDDEN_SUBSTRINGS)


def scrubbed_env(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Return a copy of ``os.environ`` with secret-bearing vars removed.

    ``extra`` values are applied last (so an explicit functional override like
    ``PYTHONDONTWRITEBYTECODE`` always wins). Pass this as ``env=`` to every
    ``subprocess.run`` / ``asyncio.create_subprocess_*`` call.
    """
    env = {k: v for k, v in os.environ.items() if not is_secret_env_name(k)}
    if extra:
        env.update(extra)
    return env


def _envelope(status, result=None, error=None, detail=None):
    return {
        "block_id": "subprocess_env_guard",
        "status": status,
        "result": result,
        "error": error,
        "detail": detail,
    }


class SubprocessEnvGuardBlock(UniversalBlock):
    """Scrubbed subprocess environment, ported from The_Fork."""

    name = "subprocess_env_guard"
    version = "1.0.0"
    description = (
        "real (clone of The_Fork app/core/subprocess_env.py): the denylist "
        "that scrubs SECRET_KEY / DATABASE_URL / *_API_KEY / *_TOKEN / "
        "*_PASSWORD / *_DSN / *_KEY family names (case-insensitive) from the "
        "environment handed to subprocesses, keeping functional system env "
        "(PATH, HOME, LANG, LC_*, TMPDIR, TESSDATA_PREFIX, PYTHON*, NODE_*). "
        "Fail-closed hardening: an extra that re-injects a secret-bearing "
        "name is refused rather than applied."
    )
    layer = 2
    tags = ["security", "process-isolation", "subprocess", "environment", "the-fork"]
    requires = []

    default_config = {}

    ui_schema = {
        "input": {
            "type": "json",
            "placeholder": '{"action": "scrub", "extra": {"PYTHONDONTWRITEBYTECODE": "1"}}',
            "multiline": True,
        },
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "result", "type": "json", "label": "Result"}]},
    }

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "")).lower()
        try:
            if action == "scrub":
                return self._scrub(payload)
            if action == "classify":
                name = payload.get("name")
                if name is None or not str(name).strip():
                    return _envelope(
                        "refused", error="classify needs an env var name to judge"
                    )
                return _envelope(
                    "ok",
                    {"name": str(name), "secret": is_secret_env_name(str(name))},
                )
            if action == "audit":
                names = payload.get("names")
                if not isinstance(names, list) or not names:
                    return _envelope(
                        "refused", error="audit needs a non-empty list of env var names"
                    )
                secret = [str(n) for n in names if is_secret_env_name(str(n))]
                return _envelope(
                    "ok",
                    {"secret": secret, "clean": [str(n) for n in names if str(n) not in secret]},
                )
            return _envelope(
                "error", error=f"unknown action: {action or '(none)'}",
                detail={"known": ["scrub", "classify", "audit"]},
            )
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=f"{type(exc).__name__}: {exc}")

    def _scrub(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        extra = payload.get("extra") or {}
        if not isinstance(extra, dict):
            return _envelope("refused", error="extra must be a {name: value} mapping")
        injected = [k for k in extra if is_secret_env_name(str(k))]
        if injected:
            return _envelope(
                "refused",
                error=(
                    f"extra carries secret-bearing name(s) {sorted(injected)}; "
                    "the donor's 'extra wins last' would re-inject a secret the "
                    "scrub exists to remove, so this block refuses instead"
                ),
                detail={"injected": sorted(injected)},
            )
        before = {k: v for k, v in os.environ.items()}
        scrubbed = scrubbed_env({str(k): str(v) for k, v in extra.items()})
        removed = sorted(k for k in before if k not in scrubbed)
        return _envelope(
            "ok",
            {"env": scrubbed, "removed_secret_names": removed, "extra_applied": dict(extra)},
        )
