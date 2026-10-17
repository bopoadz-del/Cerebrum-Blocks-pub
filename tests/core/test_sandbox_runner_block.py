"""Tests for the sandbox-runner /run_block endpoint."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# The sandbox runner is a standalone service; add its directory to the path.
SANDBOX_DIR = Path(__file__).resolve().parents[2] / "sandbox-runner"
sys.path.insert(0, str(SANDBOX_DIR))

os.environ.setdefault("BLOCK_REGISTRY_ROOT", str(Path(__file__).resolve().parents[2] / "block_registry"))

from server import app  # noqa: E402


@pytest.fixture
def client():
    return TestClient(app)


def test_run_block_construction_v2(client):
    """Run a safe registry block through the sandbox runner endpoint."""
    response = client.post(
        "/run_block",
        json={
            "block_name": "construction_v2",
            "input": "Concrete slab 10m x 5m x 0.2m",
            "params": {"default_trade": "concrete"},
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("ok", "error")


def test_run_block_missing_adapter(client):
    response = client.post("/run_block", json={"block_name": "nonexistent_block_xyz"})
    assert response.status_code == 404


def test_run_block_invalid_name(client):
    response = client.post("/run_block", json={"block_name": "../etc/passwd"})
    assert response.status_code == 400
