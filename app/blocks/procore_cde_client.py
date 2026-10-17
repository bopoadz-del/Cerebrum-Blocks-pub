"""Read-only Procore client behind the CDE door.

Donor protocol: The_Fork app/core/cde/protocol.py (CdeClient).
This block implements the read methods only.
post_mail and post_rfi refuse. They never mint a CDE id.
Unconfigured calls (missing base_url or token) return an error and make no HTTP request.
Live calls use GET /rest/v1.0/projects/{id}/documents and /rfis.
Classification: verified_executable for the fail-closed and parse paths.
It is not a certified live Procore integration.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.request import Request, urlopen

from app.core.universal_base import UniversalBlock
from app.core.http_errors import UNAVAILABLE

logger = logging.getLogger("cerebrum.blocks.procore_cde_client")


def _as_list(payload: Any) -> Optional[List]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return payload["data"]
    return None


class ProcoreCdeClientBlock(UniversalBlock):
    """Read-only Procore. Fail closed when the token or base URL is missing."""

    name = "procore_cde_client"
    version = "1.0.0"
    classification = "verified_executable"
    vendor = "procore"
    requires = []
    layer = 2
    tags = ["cde", "procore", "readonly"]
    default_config = {"read_only": True}
    ui_schema = {"input": {"type": "json"}, "output": {"type": "json"}, "params": [], "quick_actions": []}

    def __init__(self, hal_block=None, config=None):
        super().__init__(hal_block, config)
        self.base_url = ((config or {}).get("base_url") or "").rstrip("/")
        self.token = (config or {}).get("token") or ""
        self.http_get: Optional[Callable] = (config or {}).get("http_get")

    def configured(self) -> bool:
        return bool(self.base_url and self.token)

    def _request(self, path: str) -> Tuple[int, Any]:
        url = self.base_url + path
        if self.http_get is not None:
            return self.http_get(url, self.token)
        req = Request(url, method="GET", headers={"Authorization": "Bearer " + self.token})
        try:
            with urlopen(req, timeout=10) as resp:
                raw = resp.read()
                status = int(resp.status)
        except Exception as exc:
            logger.warning("procore GET failed url=%s error=%s", url, exc)
            return 0, {"error": type(exc).__name__}
        try:
            return status, json.loads(raw.decode("utf-8"))
        except Exception as exc:
            logger.warning("procore body was not json url=%s error=%s", url, exc)
            return status, {"error": "not_json"}

    def _guard(self):
        if not self.configured():
            return {"status": "error", "error": "procore not configured", "error_kind": UNAVAILABLE}
        return None

    def list_documents(self, project_id: str) -> Dict:
        denied = self._guard()
        if denied:
            return denied
        path = "/rest/v1.0/projects/%s/documents" % project_id
        status, body = self._request(path)
        rows = _as_list(body)
        if status != 200 or rows is None:
            return {"status": "error", "error": "procore list_documents failed", "http_status": status}
        return {"status": "ok", "documents": [self._document(item) for item in rows], "path": path}

    def get_document(self, project_id: str, document_id: str) -> Dict:
        denied = self._guard()
        if denied:
            return denied
        path = "/rest/v1.0/projects/%s/documents/%s" % (project_id, document_id)
        status, body = self._request(path)
        if status != 200 or not isinstance(body, dict) or "id" not in body:
            return {"status": "error", "error": "procore get_document failed", "http_status": status}
        doc = self._document(body)
        doc["path"] = path
        return {"status": "ok", "document": doc}

    def list_mail(self, project_id: str) -> Dict:
        denied = self._guard()
        if denied:
            return denied
        path = "/rest/v1.0/projects/%s/rfis" % project_id
        status, body = self._request(path)
        rows = _as_list(body)
        if status != 200 or rows is None:
            return {"status": "error", "error": "procore list_mail failed", "http_status": status}
        return {"status": "ok", "mail": [self._mail(item) for item in rows], "path": path}

    def download_document(self, project_id: str, document_id: str) -> Dict:
        denied = self._guard()
        if denied:
            return denied
        return {
            "status": "error",
            "error": "procore download not implemented",
            "project_id": project_id,
            "document_id": document_id,
        }

    def post_mail(self, project_id: str, draft: Dict) -> Dict:
        return {"status": "error", "error": "read-only; post not implemented", "project_id": project_id}

    def _document(self, item: Dict) -> Dict:
        return {
            "id": str(item.get("id")),
            "title": item.get("name") or item.get("title") or "",
            "filename": item.get("filename") or item.get("name") or "",
            "revision": str(item.get("revision") or ""),
        }

    def _mail(self, item: Dict) -> Dict:
        return {
            "id": str(item.get("id")),
            "subject": item.get("subject") or "",
            "mail_type": item.get("mail_type") or "RFI",
            "status": item.get("status") or "",
        }

    async def process(self, input_data, params=None):
        data = input_data or {}
        action = (params or {}).get("action") or data.get("action")
        project_id = str(data.get("project_id") or "")
        if action == "list_documents":
            return self.list_documents(project_id)
        if action == "get_document":
            return self.get_document(project_id, str(data.get("document_id") or ""))
        if action == "list_mail":
            return self.list_mail(project_id)
        if action == "download_document":
            return self.download_document(project_id, str(data.get("document_id") or ""))
        if action in ("post_mail", "post_rfi"):
            return self.post_mail(project_id, data.get("draft") or {})
        return {"status": "error", "error": "Unknown action: %s" % action}
