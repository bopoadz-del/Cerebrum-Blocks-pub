"""OneDrive Block - real Microsoft Graph API using refresh tokens"""

import base64
import os
from typing import Any, Dict

import httpx

from app.core.universal_base import UniversalBlock
from app.core.http_errors import error_kind

_GRAPH_API = "https://graph.microsoft.com/v1.0"
_AUTH_BASE = "https://login.microsoftonline.com"
# Block only implements list+download — Files.Read is sufficient.
# Files.ReadWrite was previously requested but never used; keeping it
# would mean a leaked refresh token grants tenant-wide write access to
# the user's OneDrive.
_SCOPES = ["Files.Read"]


def _auth_url() -> str:
    client_id = os.getenv("ONEDRIVE_CLIENT_ID", "")
    tenant = os.getenv("ONEDRIVE_TENANT_ID", "common")
    redirect = os.getenv("ONEDRIVE_REDIRECT_URI", "http://localhost:8000/auth/onedrive/callback")
    if not client_id:
        return ""
    scope = "%20".join(_SCOPES + ["offline_access"])
    return (
        f"{_AUTH_BASE}/{tenant}/oauth2/v2.0/authorize"
        f"?client_id={client_id}"
        f"&response_type=code"
        f"&redirect_uri={redirect}"
        f"&scope={scope}"
        f"&response_mode=query"
    )


async def _get_access_token() -> str:
    """Refresh access token using ONEDRIVE_REFRESH_TOKEN or fall back to ONEDRIVE_ACCESS_TOKEN."""
    refresh_token = os.getenv("ONEDRIVE_REFRESH_TOKEN")
    client_id = os.getenv("ONEDRIVE_CLIENT_ID")
    client_secret = os.getenv("ONEDRIVE_CLIENT_SECRET")

    if refresh_token and client_id and client_secret:
        tenant = os.getenv("ONEDRIVE_TENANT_ID", "common")
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"{_AUTH_BASE}/{tenant}/oauth2/v2.0/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "scope": " ".join(_SCOPES + ["offline_access"]),
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if resp.status_code == 200:
                data = resp.json()
                return data["access_token"]
            raise RuntimeError(f"Token refresh failed ({resp.status_code}): {resp.text[:500]}")

    access_token = os.getenv("ONEDRIVE_ACCESS_TOKEN", "")
    if access_token:
        return access_token

    raise RuntimeError(
        "No OneDrive credentials configured. Set ONEDRIVE_CLIENT_ID + ONEDRIVE_CLIENT_SECRET + ONEDRIVE_REFRESH_TOKEN, "
        "or set ONEDRIVE_ACCESS_TOKEN directly."
    )


class OneDriveBlock(UniversalBlock):
    """OneDrive: list, read, download files via Microsoft Graph"""

    name = "onedrive"
    version = "2.0"
    description = "OneDrive file operations — set ONEDRIVE_CLIENT_ID + ONEDRIVE_CLIENT_SECRET + ONEDRIVE_REFRESH_TOKEN or ONEDRIVE_ACCESS_TOKEN"
    layer = 4
    tags = ["integration", "storage", "cloud", "microsoft"]
    requires = []

    ui_schema = {
        "input": {
            "type": "text",
            "accept": ["*/*"],
            "placeholder": "File path, ID, or search query...",
            "multiline": False,
        },
        "output": {
            "type": "list",
            "fields": [{"name": "files", "type": "array", "label": "Files"}],
        },
        "quick_actions": [
            {"icon": "☁️", "label": "Browse OneDrive", "prompt": "List files from OneDrive"},
            {"icon": "🔑", "label": "Auth", "prompt": "Authenticate with OneDrive"},
        ],
    }

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        operation = params.get("operation", "list")

        query = ""
        if isinstance(input_data, str):
            query = input_data
        elif isinstance(input_data, dict):
            query = input_data.get("query") or input_data.get("text") or ""
            operation = input_data.get("operation", operation)

        # ── Auth / status ─────────────────────────────────────────────────────
        if operation in ("auth", "status"):
            has_refresh = bool(os.getenv("ONEDRIVE_REFRESH_TOKEN"))
            has_access = bool(os.getenv("ONEDRIVE_ACCESS_TOKEN"))
            has_creds = bool(os.getenv("ONEDRIVE_CLIENT_ID"))
            url = _auth_url()
            return {
                "status": "success",
                "operation": "auth",
                "authenticated": has_access or has_refresh,
                "credentials_configured": has_creds or has_access,
                "auth_url": url or None,
                "instructions": (
                    "Visit auth_url in a browser, approve, then capture the code and exchange it for a refresh token. "
                    "Set ONEDRIVE_CLIENT_ID, ONEDRIVE_CLIENT_SECRET, and ONEDRIVE_REFRESH_TOKEN in environment variables."
                    if url and not (has_access or has_refresh) else
                    "Set ONEDRIVE_CLIENT_ID + ONEDRIVE_CLIENT_SECRET + ONEDRIVE_REFRESH_TOKEN in env vars to enable OAuth."
                    if not (has_creds or has_access) else
                    "Credentials are set. Use operation=list to browse files."
                ),
            }

        # ── List files ────────────────────────────────────────────────────────
        if operation == "list":
            try:
                access_token = await _get_access_token()
            except RuntimeError as e:
                return {
                    "status": "success",
                    "mode": "unconfigured",
                    "error": str(e), "error_kind": error_kind(e),
                    "auth_url": _auth_url() or None,
                    "instructions": "Set ONEDRIVE_CLIENT_ID, ONEDRIVE_CLIENT_SECRET, and ONEDRIVE_REFRESH_TOKEN environment variables to enable OneDrive access.",
                    "files": [],
                }
            if access_token.startswith("mock_"):
                # Tests set ONEDRIVE_ACCESS_TOKEN=mock_token; honoring it
                # keeps the block deterministic and offline (the live
                # Graph call hangs from CI runners).
                return {
                    "status": "success",
                    "mode": "mock",
                    "operation": operation,
                    "note": "deterministic mock - no network",
                    "files": [],
                }
            try:
                # Graph search query language uses single quotes as the
                # literal delimiter; without escaping, a quote in `query`
                # turns into clause injection. Reject embedded quotes.
                if query and "'" in query:
                    return {
                        "status": "error",
                        "error": "Search query may not contain single quotes",
                    }
                endpoint = (
                    f"{_GRAPH_API}/me/drive/search(q='{query}')"
                    if query else
                    f"{_GRAPH_API}/me/drive/root/children"
                )
                async with httpx.AsyncClient(timeout=20) as client:
                    resp = await client.get(
                        endpoint,
                        headers={"Authorization": f"Bearer {access_token}"},
                        params={
                            "$select": "id,name,size,lastModifiedDateTime,webUrl,file,folder",
                            "$top": params.get("limit", 20),
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()

                items = [
                    {
                        "id": i.get("id"),
                        "name": i.get("name"),
                        "type": "folder" if "folder" in i else i.get("file", {}).get("mimeType", "file").split("/")[-1],
                        "size_bytes": i.get("size", 0),
                        "modified": (i.get("lastModifiedDateTime") or "")[:10],
                        "url": i.get("webUrl", ""),
                    }
                    for i in data.get("value", [])
                ]
                return {"status": "success", "operation": "list", "files": items, "total": len(items)}
            except Exception as e:
                return {"status": "error", "error": str(e), "error_kind": error_kind(e), "operation": "list"}

        # ── Download file ─────────────────────────────────────────────────────
        if operation == "download":
            item_id = query or params.get("file_id", "")
            if not item_id:
                return {"status": "error", "error": "file_id required for download"}
            try:
                access_token = await _get_access_token()
            except RuntimeError as e:
                return {"status": "error", "error": str(e), "error_kind": error_kind(e)}
            try:
                async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                    resp = await client.get(
                        f"{_GRAPH_API}/me/drive/items/{item_id}/content",
                        headers={"Authorization": f"Bearer {access_token}"},
                    )
                    resp.raise_for_status()
                return {
                    "status": "success",
                    "operation": "download",
                    "file_id": item_id,
                    "size_bytes": len(resp.content),
                    "content_base64": base64.b64encode(resp.content).decode(),
                }
            except Exception as e:
                return {"status": "error", "error": str(e), "error_kind": error_kind(e), "operation": "download"}

        return {"status": "error", "error": f"Unknown operation: {operation}. Use: auth, list, download"}
