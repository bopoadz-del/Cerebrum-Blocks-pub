"""Integration tests for API endpoints."""

import os

import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app, headers={"Authorization": "Bearer cb_dev_key"})

# `client` above attaches an API key to every request, which makes it
# useless for asserting that an endpoint refuses anonymous callers.
anon_client = TestClient(app)

requires_extended_blocks = pytest.mark.skipif(
    os.getenv("CEREBRUM_VIRGIN", "true").strip().lower() in ("1", "true", "yes"),
    reason="Drive blocks require legacy boot (set CEREBRUM_VIRGIN=false)",
)

class TestAPIEndpoints:
    """Test suite for API endpoints."""
    
    def test_root_endpoint(self):
        """Root serves the Console Floor pack console (the product UI).
        The JSON API metadata remains available at /api."""
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
        assert "Product Console" in response.text

        api_response = client.get("/api")
        assert api_response.status_code == 200
        data = api_response.json()
        assert data["name"] == "Cerebrum Blocks"
        assert "blocks" in data
    
    def test_list_blocks(self):
        """Test listing all blocks."""
        response = client.get("/blocks")
        assert response.status_code == 200
        data = response.json()
        assert "blocks" in data
        assert "total" in data
        # count grows as new blocks are added — just ensure minimum
        assert data["total"] >= 23
        
        # Check that vector_search is included
        block_names = [b["name"] for b in data["blocks"]]
        assert "vector_search" in block_names
    
    def test_get_block_info(self):
        """Test getting block info."""
        response = client.get("/blocks/vector_search")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "vector_search"
        assert "config" in data
    
    def test_get_nonexistent_block(self):
        """Test getting non-existent block."""
        response = client.get("/blocks/nonexistent")
        assert response.status_code == 404
    
    def test_health_endpoint(self):
        """Liveness: unauthenticated, minimal, always 200."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_readiness_endpoint(self):
        """Readiness probes real dependencies and can return non-200."""
        response = client.get("/ready")
        assert response.status_code in (200, 503)
        assert response.json()["status"] in ("ready", "degraded")

    def test_stats_endpoint_requires_auth(self):
        """/stats returns the block inventory that /blocks is gated to
        protect, so it carries the same gate.

        Note the module-level `client` sends an Authorization header on
        every request, so the unauthenticated case needs its own client.
        """
        assert anon_client.get("/stats").status_code == 401
        response = client.get("/stats")
        assert response.status_code == 200
        assert "blocks" in response.json()

    @pytest.mark.parametrize(
        "path",
        ["/stats", "/blocks", "/v1/blocks", "/v1/system/diagnostics", "/v1/system/health"],
    )
    def test_inventory_and_diagnostics_are_gated_on_the_real_app(self, path):
        """Same gate, asserted against the fully assembled app rather than
        a router-only test harness."""
        assert anon_client.get(path).status_code == 401

    @pytest.mark.parametrize("path", ["/health", "/v1/health", "/ready", "/v1/ready"])
    def test_probe_endpoints_stay_anonymous_on_the_real_app(self, path):
        """Render and Docker cannot present a bearer token."""
        assert anon_client.get(path).status_code in (200, 503)


class TestExecuteEndpoint:
    """Tests for execute endpoint."""
    
    def test_execute_chat_mock(self):
        """Test executing chat block with mock."""
        response = client.post("/execute", json={
            "block": "chat",
            "input": "Hello",
            "params": {"provider": "mock"}
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["block"] == "chat"
        assert "result" in data
    
    def test_execute_vector_search_list_collections(self):
        """Test executing vector_search block."""
        response = client.post("/execute", json={
            "block": "vector_search",
            "input": {},
            "params": {"operation": "list_collections"}
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["block"] == "vector_search"
        assert "collections" in data["result"]
    
    def test_execute_vector_search_create_collection(self):
        """Test vector_search create_collection operation."""
        response = client.post("/execute", json={
            "block": "vector_search",
            "input": "test_collection",
            "params": {"operation": "create_collection"}
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["block"] == "vector_search"
        assert data["result"]["status"] == "success"
    
    def test_execute_web_block(self):
        """Test executing web block."""
        response = client.post("/execute", json={
            "block": "web",
            "input": "<html><body>Test</body></html>",
            "params": {"operation": "html_parse"}
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["block"] == "web"
    
    def test_execute_nonexistent_block(self):
        """Test executing non-existent block."""
        response = client.post("/execute", json={
            "block": "nonexistent",
            "input": "test",
            "params": {}
        })
        
        assert response.status_code == 404
    
    def test_execute_translate_mock(self):
        """Test executing translate block with mock."""
        response = client.post("/execute", json={
            "block": "translate",
            "input": "Hello",
            "params": {"provider": "mock", "target": "es"}
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["block"] == "translate"


class TestChainEndpoint:
    """Tests for chain endpoint."""
    
    def test_chain_execution(self):
        """Test chain execution."""
        response = client.post("/chain", json={
            "steps": [
                {"block": "chat", "params": {"provider": "mock"}},
                {"block": "translate", "params": {"provider": "mock", "target": "es"}}
            ],
            "initial_input": "Hello World"
        })
        
        assert response.status_code == 200
        data = response.json()
        assert "steps_executed" in data
        assert "final_output" in data
    
    def test_empty_chain(self):
        """Test empty chain."""
        response = client.post("/chain", json={
            "steps": [],
            "initial_input": "test"
        })
        
        # Should either succeed or handle gracefully
        assert response.status_code in [200, 422]


@requires_extended_blocks
class TestDriveEndpoints:
    """Tests for drive-specific endpoints."""

    def test_local_drive_list(self):
        """Test local drive via execute endpoint."""
        response = client.post("/execute", json={
            "block": "local_drive",
            "input": "/",
            "params": {"operation": "list"}
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["block"] == "local_drive"
    
    def test_google_drive_mock(self):
        """Test Google Drive with mock."""
        response = client.post("/execute", json={
            "block": "google_drive",
            "input": {},
            "params": {"operation": "list"}
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["block"] == "google_drive"
    
    def test_onedrive_mock(self):
        """Test OneDrive with mock."""
        response = client.post("/execute", json={
            "block": "onedrive",
            "input": {},
            "params": {"operation": "list"}
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["block"] == "onedrive"
    
    def test_android_drive_paths_refuses_instead_of_fabricating(self):
        """android_drive is a stub, so get_paths must say so.

        It used to answer with fabricated device paths. Phase 1.7 replaced
        that with an honest refusal; this asserts the refusal rather than
        the invented data, so the test fails again if the stub ever starts
        making paths up.
        """
        response = client.post("/execute", json={
            "block": "android_drive",
            "input": {},
            "params": {"operation": "get_paths"}
        })

        assert response.status_code == 200
        data = response.json()
        assert data["block"] == "android_drive"
        result = data["result"]
        assert result["status"] == "error"
        assert result["error"] == "not_implemented"
        assert "paths" not in result


class TestVectorSearchEndpoints:
    """Tests for vector search specific endpoints."""
    
    def test_vector_search_count(self):
        """Test vector search count operation."""
        response = client.post("/execute", json={
            "block": "vector_search",
            "input": {},
            "params": {"operation": "count", "collection": "test"}
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["block"] == "vector_search"
        assert "count" in data["result"]
    
    def test_vector_search_create_collection(self):
        """Test vector search create collection."""
        response = client.post("/execute", json={
            "block": "vector_search",
            "input": "test_collection",
            "params": {"operation": "create_collection"}
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["block"] == "vector_search"
    
    def test_vector_search_add_documents(self):
        """Test vector search add documents."""
        response = client.post("/execute", json={
            "block": "vector_search",
            "input": {
                "documents": [
                    {"text": "Test doc 1", "metadata": {"source": "test"}},
                    {"text": "Test doc 2", "metadata": {"source": "test"}}
                ]
            },
            "params": {"operation": "add", "collection": "test"}
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["block"] == "vector_search"
        assert data["result"]["added"] == 2
