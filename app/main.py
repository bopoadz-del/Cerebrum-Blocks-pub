"""Cerebrum Blocks - Simple Block Execution API."""

import os
import sys

# Optional: clear stale bytecode at import time. Originally a workaround
# for Render redeploys keeping prior worker's __pycache__ around. Now
# gated behind CLEAR_PYCACHE=1 so we don't scan the whole tree (and miss
# the bytecode cache on every cold start) by default. Prefer setting
# PYTHONDONTWRITEBYTECODE=1 in the deploy environment instead.
if os.getenv("CLEAR_PYCACHE", "").lower() in ("1", "true", "yes"):
    import shutil as _shutil
    for _root, _dirs, _ in os.walk(os.path.dirname(os.path.abspath(__file__))):
        for _d in _dirs:
            if _d == "__pycache__":
                try:
                    _shutil.rmtree(os.path.join(_root, _d))
                except OSError:
                    pass

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

load_dotenv()

from app.core.logging_config import configure_logging, init_sentry

configure_logging()
init_sentry()

logger = logging.getLogger(__name__)

from app.core import vector_store
from app.dependencies import init_blocks
from app.routers import (
    ingestion,
    auth,
    blocks,
    capture,
    agent_swarm,
    workflow,
    knowledge,
    notification,
    chain,
    chat,
    connectors,
    debug,
    execute,
    health,
    memory,
    metrics as metrics_router,
    monitoring,
    registry,
    skills,
    static,
    store,
    upload,
    video,
    workflows,
)
from app.routers.metrics import _record_metrics
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start serving traffic immediately; warm core blocks in the background.

    Previously this blocked startup for ~2s+ (importing sklearn, sympy, etc.).
    During every redeploy, that translated into a window where Render's
    upstream returned 502 because the new worker hadn't completed lifespan
    yet. With auto-deploy on every commit, a busy session = several
    user-visible 502 spikes.

    Now: lifespan returns instantly, init_blocks() runs as a background task.
    /health and /ready respond the moment uvicorn binds (liveness does no
    I/O at all; readiness runs two cheap local checks). First /v1/execute
    call may pay
    a small lazy-import cost (10ms in our profile), but no request is ever
    blocked on a 2s+ pre-warm.
    """
    import asyncio

    from app.core import backup_scheduler

    await vector_store.init_pool()
    asyncio.create_task(init_blocks())
    # Nightly DATA_DIR backups run in-process: Render cron jobs cannot mount
    # persistent disks, so this is the only process that can take them.
    backup_task = backup_scheduler.start()
    yield
    if backup_task is not None:
        backup_task.cancel()
    await vector_store.close_pool()


app = FastAPI(
    title="Cerebrum Blocks",
    description="Build AI Like Lego - Simple Block Execution API",
    version="2.0.0",
    docs_url="/docs",
    lifespan=lifespan,
)

def _resolve_cors_origins() -> list[str]:
    """Resolve allowed origins.

    `CORS_ORIGINS` env wins when set (comma-separated). Otherwise we fall
    back to the known Render production URLs, with localhost added in dev.
    `*` is rejected when `allow_credentials=True` (browsers reject it
    anyway, but it's worth catching at config time).
    """
    raw = os.getenv("CORS_ORIGINS", "").strip()
    if raw:
        origins = [o.strip() for o in raw.split(",") if o.strip()]
        if "*" in origins:
            logger.warning(
                "CORS_ORIGINS contains '*' but allow_credentials=True. "
                "Wildcard ignored — set explicit origins instead."
            )
            origins = [o for o in origins if o != "*"]
        return origins

    env = os.getenv("ENV", os.getenv("ENVIRONMENT", "production")).strip().lower()
    defaults = [
        "https://cerebrum-platform.onrender.com",
        "https://cerebrum-platform-api.onrender.com",
        "https://cerebrum-store.onrender.com",
    ]
    if env in {"dev", "development", "local", "test", "testing"}:
        defaults += [
            "http://localhost:3000",
            "http://localhost:5173",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        ]
    return defaults


app.add_middleware(
    CORSMiddleware,
    allow_origins=_resolve_cors_origins(),
    allow_credentials=True,
    # Explicit method allowlist — `["*"]` is browser-broad and made it hard
    # to audit which verbs the API actually serves.
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    # Explicit header allowlist. Authorization carries the bearer token;
    # X-Requested-With is conventional for the SPA's fetch wrapper.
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-Requested-With",
        "X-Request-ID",
    ],
    # Surface rate-limit and request-id headers so the SPA can react
    # without hard-coding header sniffing.
    expose_headers=[
        "X-RateLimit-Limit",
        "X-RateLimit-Remaining",
        "X-RateLimit-Reset",
        "X-Request-ID",
    ],
    max_age=600,
)

# Marks the in-flight request context so the block-resolution tier gate can fail
# closed on an unauthenticated/unknown-tier request (see core/security.py). Raw
# ASGI middleware — contextvars must propagate into the endpoint.
from app.core.security import RequestContextMiddleware  # noqa: E402
app.add_middleware(RequestContextMiddleware)


# Security headers middleware — adds the standard browser-side defences.
# Only applies to top-level FastAPI routes; the /mcp Starlette mount
# below has its own auth gate which adds its own response shape.
@app.middleware("http")
async def _security_headers(request, call_next):
    response = await call_next(request)
    # HSTS: tell browsers to only use HTTPS for this origin. preload-eligible
    # but conservative on duration to avoid lock-in if we ever roll back to
    # HTTP for debugging.
    response.headers.setdefault(
        "Strict-Transport-Security",
        "max-age=31536000; includeSubDomains",
    )
    # Block clickjacking. The API has no UI, so DENY is fine.
    response.headers.setdefault("X-Frame-Options", "DENY")
    # Stop browsers from MIME-sniffing JSON responses.
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    # Don't leak the API URL into Referer when the SPA cross-links out.
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    # Modern browsers don't honour X-XSS-Protection, but the value
    # "0" disables broken legacy filters that hurt more than help.
    response.headers.setdefault("X-XSS-Protection", "0")
    return response


# Prometheus metrics middleware — registered after security headers so
# the response we time and label is the one the client actually receives
# (post-header-injection). Defined in app/routers/metrics.py so the
# router and middleware live next to the metric definitions.
app.middleware("http")(_record_metrics)


# NOTE: a previous /upload security middleware lived here. It tried to
# json.loads() the request body to feed a `security` block, but /upload is
# multipart (FormData), so the JSON decode silently failed and validation
# never ran. Worse, the middleware also buffered the entire upload body
# into memory just to discard it. The route handler in upload.py already
# enforces size, extension, MIME, and traversal-safe filenames — so the
# middleware was dead weight at best and a memory hazard at worst. Removed.


# Include all routers
app.include_router(blocks.router)
app.include_router(execute.router)
app.include_router(chain.router)
app.include_router(chat.router)
app.include_router(upload.router)
app.include_router(ingestion.router)
app.include_router(auth.router)
app.include_router(memory.router)
app.include_router(metrics_router.router)
app.include_router(monitoring.router)
app.include_router(health.router)
# Console Floor pack — the ONE console UI at / plus /v1/capabilities and
# /v1/store/packs. Mounted before the static router so the console wins at /.
try:
    from app.pack_console.router import router as pack_console_router
    app.include_router(pack_console_router)
except Exception as _pack_exc:  # pragma: no cover - pack absent
    logger.warning("Console Floor pack not mounted: %s", _pack_exc)
app.include_router(static.router)
app.include_router(capture.router)
app.include_router(agent_swarm.router)
app.include_router(workflow.router)
app.include_router(knowledge.router)
app.include_router(skills.router)
app.include_router(notification.router)
app.include_router(store.router)
app.include_router(registry.router)
app.include_router(video.router)
app.include_router(workflows.router)
app.include_router(connectors.router)

# Debug routes — only in non-production environments
env = os.getenv("ENV", os.getenv("ENVIRONMENT", "production")).strip().lower()
if env in {"dev", "development", "local", "test", "testing"}:
    app.include_router(debug.router)

# Mount MCP SSE endpoint (Model Context Protocol).
# Wrapped in asgi_auth_required so the SSE transport requires Bearer
# auth + tier=unlimited (master key only by default). Previously the
# mount was unauthenticated — anyone on the public internet could call
# any block as an MCP tool, including the RCE-shaped ones (code,
# sandbox, formula_executor, secrets, database, web, webhook).
# Override via env CEREBRUM_MCP_REQUIRED_TIER or
# CEREBRUM_MCP_DISABLE_AUTH=1 (local stdio testing only).
try:
    from app.mcp_server import app_sse as mcp_app
    from app.core.security import asgi_auth_required
    app.mount("/mcp", asgi_auth_required(mcp_app))
except Exception:
    logger.exception("MCP server not mounted")

# Mount static files (graceful fallback if directory missing)
import os
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
else:
    logger.warning("Static directory %s not found — skipping StaticFiles mount", static_dir)
