"""Tests for the Prometheus `/metrics` endpoint and middleware.

We assert:
  * GET /metrics returns 200 in Prometheus exposition format.
  * The body advertises the custom `cerebrum_*` metric names.
  * After hitting an instrumented route (`/health`), the per-request
    counter records a sample tagged with the route template `/health`.
"""

from __future__ import annotations

import pytest
from prometheus_client import CONTENT_TYPE_LATEST
from starlette.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    # `with` triggers FastAPI lifespan, which kicks off init_blocks() in
    # the background. We don't need the warmup to finish for these tests
    # — just need /health and /metrics to route.
    with TestClient(app) as c:
        yield c


def test_metrics_endpoint_returns_prometheus_format(client: TestClient) -> None:
    resp = client.get("/metrics")
    assert resp.status_code == 200
    # Prometheus content-type carries a `version` parameter — match the
    # constant exactly rather than hard-coding the version string so the
    # assertion survives a prometheus_client upgrade.
    assert resp.headers["content-type"] == CONTENT_TYPE_LATEST


def test_metrics_body_lists_custom_metric_names(client: TestClient) -> None:
    body = client.get("/metrics").text
    # Custom metric names are emitted as HELP/TYPE lines even before any
    # sample is recorded, so this works on a cold scrape.
    assert "cerebrum_http_requests_total" in body
    assert "cerebrum_http_request_duration_seconds" in body
    assert "cerebrum_block_executions_total" in body
    assert "cerebrum_active_blocks" in body


def test_request_counter_records_health_hit(client: TestClient) -> None:
    health_resp = client.get("/health")
    assert health_resp.status_code == 200

    metrics_body = client.get("/metrics").text

    # We expect a sample line shaped like:
    #   cerebrum_http_requests_total{method="GET",path="/health",status_code="200"} 1.0
    # Field order isn't guaranteed, so just check the substring fragments.
    assert 'cerebrum_http_requests_total{' in metrics_body
    assert 'path="/health"' in metrics_body
    assert 'method="GET"' in metrics_body
    assert 'status_code="200"' in metrics_body


def test_metrics_endpoint_excluded_from_self_instrumentation(client: TestClient) -> None:
    """Scraping `/metrics` should not inflate the `/metrics` request counter.

    If it did, every Prometheus scrape would create an unbounded growing
    sample for path="/metrics", which is both useless and noisy.
    """
    # Hit it twice to be sure.
    client.get("/metrics")
    client.get("/metrics")
    body = client.get("/metrics").text
    # Check that no http_requests_total sample tags path="/metrics".
    for line in body.splitlines():
        if line.startswith("cerebrum_http_requests_total{"):
            assert 'path="/metrics"' not in line, line
