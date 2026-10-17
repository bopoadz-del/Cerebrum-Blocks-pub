"""HTTP surface for the exact-id REUSE present? query."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import registry as registry_router


DEV_KEY = "cb_dev_key"
AUTH_HEADER = {"Authorization": f"Bearer {DEV_KEY}"}


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(registry_router.router)
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize(
    "path",
    [
        "/v1/registry/blocks/document_engine",
        "/v1/registry/reuse/document_engine",
        "/registry/blocks/document_engine",
    ],
)
def test_present_id_returns_manifest_and_brief_scope(client, path):
    response = client.get(path, headers=AUTH_HEADER)
    assert response.status_code == 200
    data = response.json()
    assert data["present"] is True
    assert data["reuse"] is True
    assert data["id"] == "document_engine"
    assert data["manifest"]["id"] == "document_engine"
    for field in ("reads", "writes", "never", "acceptance"):
        assert isinstance(data[field], list)
        assert field in data["manifest"]


def test_absent_id_is_200_with_present_false(client):
    """A miss is a negative inventory answer, not a 404."""
    response = client.get(
        "/v1/registry/blocks/no_such_block_in_the_store",
        headers=AUTH_HEADER,
    )
    assert response.status_code == 200
    assert response.json() == {
        "present": False,
        "id": "no_such_block_in_the_store",
        "reuse": False,
    }


@pytest.mark.parametrize(
    "path",
    [
        "/v1/registry/blocks/document_engine",
        "/v1/registry/reuse/document_engine",
        "/registry/blocks/document_engine",
    ],
)
def test_registry_lookup_is_auth_gated(client, path):
    assert client.get(path).status_code == 401
