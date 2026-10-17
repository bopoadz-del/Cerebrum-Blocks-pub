"""Prometheus metrics endpoint and per-request middleware.

Exposes the standard `/metrics` endpoint in Prometheus text exposition
format, plus a small set of custom counters/histograms/gauges named in
the `cerebrum_*` namespace. Other code paths import these objects
directly (e.g. `block_executions_total.labels(block, status).inc()`).

The endpoint is intentionally unauthenticated — Prometheus scrapers
expect to hit it without a Bearer token. Restrict access at the network
layer (Render private network or an IP allowlist middleware).
"""

from __future__ import annotations

import time
from typing import Awaitable, Callable

from fastapi import APIRouter, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    REGISTRY,
    generate_latest,
)
from starlette.requests import Request
from starlette.responses import Response as StarletteResponse

router = APIRouter()


# Custom metrics — these are imported and used by other code paths.
# Naming: cerebrum_<area>_<verb>_<unit>.
http_requests_total = Counter(
    "cerebrum_http_requests_total",
    "Total HTTP requests by method, path, status_code.",
    ["method", "path", "status_code"],
)

http_request_duration_seconds = Histogram(
    "cerebrum_http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

block_executions_total = Counter(
    "cerebrum_block_executions_total",
    "Block executions by name and status.",
    ["block", "status"],
)

active_blocks = Gauge(
    "cerebrum_active_blocks",
    "Currently instantiated block instances.",
)


@router.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    """Prometheus exposition format.

    Unauthenticated by design — your Prometheus scraper hits this;
    restrict at the network layer (Render private network, or add a
    middleware that limits to internal IPs).
    """
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


def _route_template(request: Request) -> str:
    """Pick a low-cardinality label for the `path` dimension.

    Prefer the matched FastAPI route template (e.g. `/v1/blocks/{name}`
    rather than the resolved URL `/v1/blocks/formula_executor`) so id
    paths don't blow up the time series cardinality. Falls back to the
    raw URL path when no route matched (404, OPTIONS pre-match, etc.).
    """
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    if template:
        return template
    return request.url.path


async def _record_metrics(
    request: Request,
    call_next: Callable[[Request], Awaitable[StarletteResponse]],
) -> StarletteResponse:
    """ASGI middleware that times the request and records counters.

    Registered via `app.middleware("http")(_record_metrics)` from
    `app/main.py`. Skips its own `/metrics` endpoint so a Prometheus
    scrape doesn't pollute the very histograms it exposes.
    """
    path = request.url.path
    if path == "/metrics":
        return await call_next(request)

    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        elapsed = time.perf_counter() - start
        # We only know the route template after the routing layer ran,
        # which is during call_next — that's why this read sits below.
        label_path = _route_template(request)
        method = request.method
        http_requests_total.labels(
            method=method, path=label_path, status_code=str(status_code)
        ).inc()
        http_request_duration_seconds.labels(
            method=method, path=label_path
        ).observe(elapsed)
