"""Liveness, readiness, and authenticated diagnostics.

Three distinct concerns, deliberately kept apart:

* **Liveness** (`/health`, `/v1/health`) — unauthenticated, zero I/O,
  always 200. Answers only "is the process accepting requests". Render's
  deploy gate and the Docker HEALTHCHECK poll this continuously, so it
  must stay trivial; `app/dependencies.py::init_blocks` documents what
  happens when it is not (workers killed mid-pre-warm).
* **Readiness** (`/ready`, `/v1/ready`) — unauthenticated (a platform
  probe cannot present a bearer token) but non-revealing: check names and
  a pass/fail only. Returns 503 when a load-bearing dependency is broken
  so the platform can actually fail a health check. The previous
  `/health` returned "healthy" unconditionally, so a service with an
  unwritable data disk looked identical to a working one.
* **Diagnostics** (`/v1/system/diagnostics`, `/stats`,
  `/v1/system/health`) — authenticated. The audit found the old
  unauthenticated `/health` shelled out to the Kimi CLI on every probe
  and returned its stdout, its stderr, and the raw value of the
  KIMI_CLI_PATH env var to any caller, while also returning the full
  block inventory that `app/routers/blocks.py` is deliberately auth-gated
  to protect. Both now require a key, and the subprocess is TTL-cached
  off the probe path entirely.
"""

import logging
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.blocks import BLOCK_REGISTRY
from app.dependencies import (
    block_instances,
    MONITORING_AVAILABLE,
    get_monitoring_block,
    require_api_key,
)

logger = logging.getLogger("cerebrum.blocks.health")

router = APIRouter()


# ── Liveness ──────────────────────────────────────────────────────────────

@router.get("/health")
def health():
    """Liveness probe. No auth, no I/O, no dependency reveal."""
    return {"status": "ok"}


@router.get("/v1/health")
def health_v1():
    """Liveness probe (v1 API)."""
    return health()


def _sha_from_env() -> Optional[str]:
    return (os.getenv("RENDER_GIT_COMMIT") or os.getenv("GIT_COMMIT") or "").strip() or None


def _sha_from_git() -> Optional[str]:
    """Local-checkout fallback. Import-time only — never the request path.

    RENDER_GIT_COMMIT is set by the platform on every deploy; this probe
    is for a local checkout. Forking git from a request handler is both
    slow and, under TestClient, deadlock-prone. Import is still
    single-threaded.
    """
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=2,
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception as exc:  # noqa: BLE001 -- unknown is reported, never raised
        # Degraded, but VISIBLY degraded: /version answering null because git
        # is missing and /version answering null because nobody set the env
        # are different problems, and a silent pass makes them the same one.
        logger.warning("build sha unresolved (%s); /version reports null", exc)
    return None


#: Resolved once, before any TestClient or worker thread exists.
_GIT_FALLBACK_SHA = _sha_from_git()


def _build_sha() -> Optional[str]:
    return _sha_from_env() or _GIT_FALLBACK_SHA


@router.get("/version")
def version():
    """Which commit is actually serving. No auth: it is a deploy fact.

    Every claim about this service in a report has had to say COULD NOT
    VERIFY for the deployed SHA, because no HTTP route exposed it and only
    the Render dashboard could settle it. The Factory publishes the same
    route (api.cerebrum-dev.com/version) and that is the difference between
    "the fix is merged" and "the fix is live".

    ``git_sha`` is null when neither the platform env nor a git checkout can
    answer -- reported as unknown rather than guessed.
    """
    sha = _build_sha()
    return {
        "service": "cerebrum-blocks",
        "git_sha": sha,
        "git_sha_short": sha[:7] if sha else None,
        "env": os.getenv("ENV", "").strip() or None,
    }


# ── Readiness ─────────────────────────────────────────────────────────────

def _check_data_dir_writable() -> bool:
    """Can the service actually persist state? Rate limits, the grounding
    audit store and uploads all land under DATA_DIR; if it is not
    writable the service is broken even though it still answers HTTP."""
    data_dir = os.getenv("DATA_DIR", "./data")
    # Unique per probe: Render's health checker and the Docker HEALTHCHECK
    # can be in flight at the same time, and a shared filename would let
    # one probe delete the other's file and report a false "degraded" —
    # which, now that readiness gates deploys, would fail a good deploy.
    probe_path = os.path.join(
        data_dir, f".readiness_probe.{os.getpid()}.{threading.get_ident()}"
    )
    try:
        os.makedirs(data_dir, exist_ok=True)
        with open(probe_path, "w", encoding="utf-8") as fh:
            fh.write("ok")
    except OSError:
        return False
    except Exception:  # noqa: BLE001 - a probe must never raise
        return False
    finally:
        # Cleanup failure does not mean the directory is unwritable.
        try:
            os.remove(probe_path)
        except OSError:
            pass
    return True


def _check_block_registry() -> bool:
    """A platform with no blocks registered cannot serve /v1/execute."""
    try:
        return len(BLOCK_REGISTRY) > 0
    except Exception:  # noqa: BLE001 - a probe must never raise
        return False


# Only genuinely load-bearing dependencies belong here. Redis, the LLM
# provider and the corpus are all optional or externally flaky; a probe
# that flaps is worse than no probe, because the platform starts ignoring
# it (or restart-loops a service that was fine).
_READINESS_CHECKS = {
    "data_dir": _check_data_dir_writable,
    "block_registry": _check_block_registry,
}


def _run_readiness_checks() -> Dict[str, bool]:
    return {name: bool(fn()) for name, fn in _READINESS_CHECKS.items()}


def _readiness_response() -> JSONResponse:
    """Build the readiness payload.

    Deliberately minimal: check names and ok/fail. No filesystem paths, no
    env values, no exception text, no inventory counts — this endpoint is
    unauthenticated, so its degraded body must leak no more than its
    healthy one. Operators get the detail from
    `/v1/system/diagnostics`, which requires a key.
    """
    checks = _run_readiness_checks()
    ready = all(checks.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ready" if ready else "degraded",
            "checks": {n: ("ok" if ok else "fail") for n, ok in checks.items()},
        },
    )


@router.get("/ready")
def ready():
    """Readiness probe. Non-200 when a dependency is broken."""
    return _readiness_response()


@router.get("/v1/ready")
def ready_v1():
    """Readiness probe (v1 API)."""
    return _readiness_response()


# ── Diagnostics (authenticated) ───────────────────────────────────────────

# The Kimi CLI probe spawns a subprocess. The old code ran it on every
# unauthenticated /health hit, which Render polls continuously — a free
# process-spawn DoS. It is now cached and only reachable behind auth.
_KIMI_PROBE_TTL_SECONDS = float(os.getenv("KIMI_PROBE_TTL_SECONDS", "300"))
_kimi_probe_lock = threading.Lock()
_kimi_probe_cache: Optional[Tuple[float, dict]] = None


def _run_kimi_probe() -> dict:
    """Evaluated workbench capability: a registered block is not a
    capability unless the Kimi CLI actually answers.

    Failure is reported as a reason code. The previous version returned
    raw subprocess stderr and interpolated the KIMI_CLI_PATH env value
    into the message, disclosing host filesystem layout to unauthenticated
    callers.
    """
    probe = {"registered": "workbench" in BLOCK_REGISTRY, "cli_ok": False}
    cli = os.getenv("KIMI_CLI_PATH", "kimi").strip() or "kimi"
    try:
        proc = subprocess.run(
            [cli, "--version"], capture_output=True, text=True, timeout=5, check=False
        )
        probe["cli_ok"] = proc.returncode == 0
        if proc.returncode == 0:
            probe["cli_version"] = (proc.stdout or "").strip()[:80]
        else:
            probe["reason"] = "cli_exit_nonzero"
    except FileNotFoundError:
        probe["reason"] = "cli_not_found"
    except subprocess.TimeoutExpired:
        probe["reason"] = "cli_timeout"
    except Exception:  # noqa: BLE001 - health probes must not raise
        probe["reason"] = "probe_error"
    return probe


def probe_kimi_cli(force: bool = False) -> dict:
    """TTL-cached Kimi CLI probe. `force=True` bypasses the cache."""
    global _kimi_probe_cache
    now = time.monotonic()
    with _kimi_probe_lock:
        if not force and _kimi_probe_cache is not None:
            cached_at, cached = _kimi_probe_cache
            if now - cached_at < _KIMI_PROBE_TTL_SECONDS:
                return dict(cached)
    result = _run_kimi_probe()
    with _kimi_probe_lock:
        _kimi_probe_cache = (now, dict(result))
    return result


def reset_kimi_probe_cache() -> None:
    """Drop the cached probe. Used by tests and by /v1/system/diagnostics
    when an operator explicitly asks for a fresh reading."""
    global _kimi_probe_cache
    with _kimi_probe_lock:
        _kimi_probe_cache = None


@router.get("/v1/system/diagnostics")
def diagnostics(refresh: bool = False, auth: dict = Depends(require_api_key)):
    """Detailed service diagnostics. Requires a valid API key."""
    from app.core import backup_scheduler

    checks = _run_readiness_checks()
    last_backup = backup_scheduler.last_status()
    return {
        "status": "ready" if all(checks.values()) else "degraded",
        "checks": {n: ("ok" if ok else "fail") for n, ok in checks.items()},
        "blocks_loaded": len(block_instances),
        "blocks_available": len(BLOCK_REGISTRY),
        "kimi_workbench": probe_kimi_cli(force=refresh),
        "last_backup": {"ok": bool(last_backup.get("ok")), "at": last_backup.get("at")}
        if last_backup
        else None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/stats")
def stats(auth: dict = Depends(require_api_key)):
    """Platform stats. Auth required — this returns the same block
    inventory that /blocks is gated to protect, and leaking it enables
    targeted attacks on the most exploitable blocks."""
    return {
        "blocks": [name for name in BLOCK_REGISTRY.keys() if not name.startswith("container_")],
        "total_blocks": len(BLOCK_REGISTRY),
        "version": "2.0.0",
    }


@router.get("/v1/system/health")
async def full_health(auth: dict = Depends(require_api_key)):
    """Complete system health with predictions. Requires a valid API key
    — the monitoring block's report is internal state."""
    if not MONITORING_AVAILABLE:
        return diagnostics(auth=auth)
    block = get_monitoring_block()
    return await block.execute({"action": "health_report"})
