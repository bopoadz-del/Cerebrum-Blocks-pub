"""Security regression: /ingestion/text must not honor a caller-supplied path.

Before this guard, ``ingestion_text`` did ``open(request.source_path, "w")``
with an untrusted path, so any API-key holder could overwrite arbitrary files
(e.g. application code -> RCE). The write happens before the vector-store call,
so this side effect is observable even without a database: we only assert that
a path *outside* DATA_DIR is never written, whatever the ingestion result.
"""

from __future__ import annotations

import os

from fastapi.testclient import TestClient

from app.main import app
from app.routers.ingestion import DATA_DIR


def _auth_client() -> TestClient:
    return TestClient(app, headers={"Authorization": "Bearer cb_dev_key"})


def test_ingestion_text_ignores_caller_supplied_source_path(tmp_path):
    # A sentinel path well outside DATA_DIR that an attacker would target.
    evil = tmp_path / "escaped.txt"
    assert not evil.exists()

    with _auth_client() as client:
        # The response may be 200 or a 503 (no DB) — irrelevant. What matters is
        # that the untrusted path was NOT written by the endpoint.
        client.post(
            "/ingestion/text",
            json={
                "tenant_id": "sec-test",
                "project_name": "sec",
                "title": "pwn",
                "text": "PWNED",
                "source_path": str(evil),
            },
        )

    assert not evil.exists(), (
        "arbitrary file write: /ingestion/text wrote to a caller-supplied path "
        "outside DATA_DIR"
    )


def test_ingestion_text_traversal_out_of_data_dir_is_not_written(tmp_path):
    # Even a traversal string that resolves outside DATA_DIR must be inert.
    target = tmp_path / "traversed.txt"
    rel = os.path.relpath(target, DATA_DIR)  # e.g. ..\..\...\traversed.txt

    with _auth_client() as client:
        client.post(
            "/ingestion/text",
            json={
                "tenant_id": "sec-test",
                "project_name": "sec",
                "title": "pwn",
                "text": "PWNED",
                "source_path": rel,
            },
        )

    assert not target.exists(), (
        "path traversal: /ingestion/text resolved a caller path outside DATA_DIR"
    )
