"""Google Drive Block - real OAuth 2.0 + Drive API (service account or user token)"""

import json
import os
from typing import Any, Dict

from app.core.universal_base import UniversalBlock

_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
_OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
_DRIVE_API = "https://www.googleapis.com/drive/v3"


def _build_service(access_token: str = None):
    """Build an authenticated Drive HTTP client."""
    import httpx
    token = access_token or os.getenv("GOOGLE_ACCESS_TOKEN", "")
    if not token:
        raise ValueError("No access token — call with operation=auth first")
    return httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token}"},
        base_url=_DRIVE_API,
        timeout=20,
    )


def _load_service_account() -> Dict | None:
    """Service-account credentials for unattended (service-to-service)
    Drive access. GOOGLE_SERVICE_ACCOUNT_JSON is either the JSON credential
    blob itself or a path to it. None when not configured."""
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        return None
    if not raw.startswith("{"):
        path = raw
        if not os.path.exists(path):
            return None
        raw = open(path, encoding="utf-8").read()
    try:
        sa = json.loads(raw)
    except (ValueError, TypeError) as exc:
        import logging

        logging.getLogger(__name__).warning(
            "GOOGLE_SERVICE_ACCOUNT_JSON is set but not parseable: %s", exc
        )
        return None
    if sa.get("client_email") and sa.get("private_key"):
        return sa
    return None


def _service_account_jwt(sa: Dict) -> str:
    """Mint a JWT bearer assertion signed with the SA private key (RS256)."""
    import base64
    import time

    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    def _b64(blob: bytes) -> str:
        return base64.urlsafe_b64encode(blob).rstrip(b"=").decode()

    header = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    now = int(time.time())
    claims = _b64(
        json.dumps(
            {
                "iss": sa["client_email"],
                "scope": " ".join(_SCOPES),
                "aud": sa.get("token_uri", _OAUTH_TOKEN_URL),
                "iat": now,
                "exp": now + 3600,
            }
        ).encode()
    )
    signing_input = f"{header}.{claims}"
    key = serialization.load_pem_private_key(
        sa["private_key"].encode(), password=None
    )
    signature = key.sign(
        signing_input.encode(), padding.PKCS1v15(), hashes.SHA256()
    )
    return f"{signing_input}.{_b64(signature)}"


async def _service_account_token(sa: Dict) -> str:
    """Exchange the JWT assertion for an access token (jwt-bearer grant)."""
    import httpx

    assertion = _service_account_jwt(sa)
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            sa.get("token_uri", _OAUTH_TOKEN_URL),
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
        )
        if resp.status_code == 200:
            return resp.json()["access_token"]
        raise RuntimeError(
            f"Service-account token exchange failed ({resp.status_code}): "
            f"{resp.text[:500]}"
        )


def _auth_mode() -> str:
    """Which credential path is active: service_account / user_token / none."""
    if _load_service_account():
        return "service_account"
    if os.getenv("GOOGLE_ACCESS_TOKEN") or os.getenv("GOOGLE_REFRESH_TOKEN"):
        return "user_token"
    return "unconfigured"


async def _get_access_token() -> str:
    """Refresh an access token, or fall back to GOOGLE_ACCESS_TOKEN.

    Mirrors onedrive._get_access_token so both drive blocks authenticate the
    same way. A long-lived GOOGLE_ACCESS_TOKEN expires in an hour, so a
    deployment that only ever sets that variable stops working silently after
    the first hour; the refresh grant is what makes it keep working.
    """
    import httpx

    service_account = _load_service_account()
    if service_account:
        # Unattended service-to-service access: no user OAuth, no browser.
        return await _service_account_token(service_account)

    refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN")
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")

    if refresh_token and client_id and client_secret:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                _OAUTH_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if resp.status_code == 200:
                return resp.json()["access_token"]
            raise RuntimeError(
                f"Token refresh failed ({resp.status_code}): {resp.text[:500]}"
            )

    token = os.getenv("GOOGLE_ACCESS_TOKEN", "")
    if not token:
        raise RuntimeError(
            "No Google credentials: set GOOGLE_REFRESH_TOKEN + GOOGLE_CLIENT_ID "
            "+ GOOGLE_CLIENT_SECRET, or GOOGLE_ACCESS_TOKEN."
        )
    return token


def _reject_quote(value: str, field: str) -> Dict | None:
    """Drive Query Language delimits literals with single quotes.

    ``name contains '<query>'`` with an unescaped quote in <query> closes the
    literal and everything after it is parsed as query syntax -- so a search
    box becomes a way to enumerate files the caller was never shown, e.g.
    ``' or trashed=false or '``. Google offers no parameter binding here, and
    a lone backslash-escape is easy to get subtly wrong, so the block refuses
    the character outright. onedrive.py already does exactly this; google_drive
    did not, which is the whole of the bug.
    """
    if value and "'" in value:
        return {
            "status": "error",
            "error": f"{field} may not contain single quotes",
        }
    return None


def _oauth_url() -> str:
    client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    if not client_id:
        return ""
    redirect = os.getenv("GOOGLE_REDIRECT_URI", "urn:ietf:wg:oauth:2.0:oob")
    scope = " ".join(_SCOPES)
    return (
        f"{_OAUTH_AUTH_URL}?client_id={client_id}"
        f"&redirect_uri={redirect}"
        f"&response_type=code"
        f"&scope={scope}"
        f"&access_type=offline"
    )


class GoogleDriveBlock(UniversalBlock):
    """Google Drive: list, read, download files via OAuth 2.0"""

    name = "google_drive"
    version = "2.0"
    description = "Google Drive file operations — set GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET or GOOGLE_ACCESS_TOKEN"
    layer = 4
    tags = ["integration", "storage", "cloud", "google"]
    requires = []

    ui_schema = {
        "input": {
            "type": "text",
            "accept": ["*/*"],
            "placeholder": "File ID, folder name, or search query...",
            "multiline": False,
        },
        "output": {
            "type": "list",
            "fields": [{"name": "files", "type": "array", "label": "Files"}],
        },
        "quick_actions": [
            {"icon": "️", "label": "Browse Drive", "prompt": "List files from Google Drive"},
            {"icon": "", "label": "Auth", "prompt": "Authenticate with Google Drive"},
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

        # ── Auth status / URL ─────────────────────────────────────────────────
        if operation in ("auth", "status"):
            has_token = bool(os.getenv("GOOGLE_ACCESS_TOKEN"))
            has_creds = bool(os.getenv("GOOGLE_CLIENT_ID"))
            url = _oauth_url()
            return {
                "status": "success",
                "operation": "auth",
                "authenticated": has_token or bool(_load_service_account()),
                "credentials_configured": has_creds or bool(_load_service_account()),
                "mode": _auth_mode(),
                "auth_url": url or None,
                "instructions": (
                    "Visit auth_url in a browser, approve, then set GOOGLE_ACCESS_TOKEN env var with the returned token."
                    if url and not has_token else
                    "Set GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET as env vars to enable OAuth."
                    if not has_creds else
                    "Access token is set. Use operation=list to browse files."
                ),
            }

        # ── List files ────────────────────────────────────────────────────────
        if operation == "list":
            # Validate before authenticating: a bad query is bad regardless of
            # who is asking, and checking after the token would make this
            # unreachable wherever the refresh grant raises first.
            bad = _reject_quote(query, "Search query") or _reject_quote(
                params.get("folder_id") or "", "folder_id"
            )
            if bad:
                return bad

            access_token = params.get("access_token") or os.getenv("GOOGLE_ACCESS_TOKEN", "")
            if not access_token:
                try:
                    access_token = await _get_access_token()
                except Exception as exc:  # noqa: BLE001
                    return {
                        "status": "error",
                        "error": f"Not authenticated: {exc}",
                        "auth_url": _oauth_url() or None,
                    }
            try:
                import httpx
                # Build the Drive-API q filter. Search wins if present (name
                # contains, no folder filter); otherwise list children of a
                # specific folder (defaults to root so the user sees their
                # actual top-level Drive, not the 50 newest files at any
                # depth which was the prior behaviour).
                folder_id = params.get("folder_id")
                if query:
                    q = f"name contains '{query}' and trashed=false"
                elif folder_id:
                    q = f"'{folder_id}' in parents and trashed=false"
                else:
                    q = "'root' in parents and trashed=false"
                async with httpx.AsyncClient(timeout=20) as client:
                    resp = await client.get(
                        f"{_DRIVE_API}/files",
                        headers={"Authorization": f"Bearer {access_token}"},
                        params={
                            "q": q,
                            "pageSize": params.get("limit", 100),
                            "orderBy": "folder,name",  # folders first, then alpha
                            "fields": "files(id,name,mimeType,size,modifiedTime,webViewLink,parents)",
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()

                FOLDER_MT = "application/vnd.google-apps.folder"
                files = [
                    {
                        "id": f.get("id"),
                        "name": f.get("name"),
                        "mime_type": f.get("mimeType", ""),
                        "is_folder": f.get("mimeType") == FOLDER_MT,
                        "type": f.get("mimeType", "").split("/")[-1],
                        "size_bytes": int(f.get("size", 0)),
                        "modified": f.get("modifiedTime", "")[:10],
                        "url": f.get("webViewLink", ""),
                    }
                    for f in data.get("files", [])
                ]
                return {"status": "success", "operation": "list", "mode": _auth_mode(), "files": files, "total": len(files)}
            except Exception:
                return {
                    "status": "error",
                    "error": "Unable to list Google Drive files at this time.",
                    "operation": "list",
                }

        # ── Download / read file ──────────────────────────────────────────────
        if operation == "download":
            file_id = query or params.get("file_id", "")
            access_token = params.get("access_token") or os.getenv("GOOGLE_ACCESS_TOKEN", "")
            if not file_id:
                return {"status": "error", "error": "file_id required for download"}
            if not access_token:
                try:
                    access_token = await _get_access_token()
                except Exception as exc:  # noqa: BLE001
                    return {"status": "error", "error": f"Not authenticated: {exc}"}
            try:
                import httpx
                from app.core import drive_mime
                async with httpx.AsyncClient(timeout=60) as client:
                    meta = await client.get(
                        f"{_DRIVE_API}/files/{file_id}",
                        headers={"Authorization": f"Bearer {access_token}"},
                        params={"fields": "mimeType,name"},
                    )
                    meta.raise_for_status()
                    mime = meta.json().get("mimeType", "")
                    target = drive_mime.export_target(mime)
                    if target is not None:
                        export_mime, exported_ext = target
                        resp = await client.get(
                            f"{_DRIVE_API}/files/{file_id}/export",
                            headers={"Authorization": f"Bearer {access_token}"},
                            params={"mimeType": export_mime},
                        )
                    else:
                        exported_ext = None
                        resp = await client.get(
                            f"{_DRIVE_API}/files/{file_id}",
                            headers={"Authorization": f"Bearer {access_token}"},
                            params={"alt": "media"},
                        )
                    resp.raise_for_status()
                    content = resp.content
                return {
                    "status": "success",
                    "operation": "download",
                    "file_id": file_id,
                    "mime_type": mime,
                    "exported_extension": exported_ext,
                    "size_bytes": len(content),
                    "content_base64": __import__("base64").b64encode(content).decode(),
                }
            except Exception:
                return {
                    "status": "error",
                    "error": "Unable to download Google Drive file at this time.",
                    "operation": "download",
                }

        return {"status": "error", "error": f"Unknown operation: {operation}. Use: auth, list, download"}
