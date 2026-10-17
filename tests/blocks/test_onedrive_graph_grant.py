"""OneDrive block: the real refresh-token grant and the real Graph payloads.

Everything here runs offline against a faked httpx transport (the pattern in
tests/blocks/test_sandbox_isolated_requires_runner.py). No live credentials and
no network: the transport records exactly what the block sent and hands back a
response the block then has to parse.

These tests exist because tests/blocks/test_onedrive.py asserts only the
UniversalBlock envelope, which execute() supplies whatever process() returns.
Every assertion below names a value the block itself had to compute: the token
endpoint it built, the form fields and scope it sent, the bearer it lifted out
of the grant response, the Graph URL it assembled, and the file rows it mapped.
"""

from __future__ import annotations

import base64

import httpx
import pytest

from app.blocks.onedrive import OneDriveBlock

_ONEDRIVE_VARS = (
    "ONEDRIVE_CLIENT_ID",
    "ONEDRIVE_CLIENT_SECRET",
    "ONEDRIVE_REFRESH_TOKEN",
    "ONEDRIVE_ACCESS_TOKEN",
    "ONEDRIVE_TENANT_ID",
    "ONEDRIVE_REDIRECT_URI",
)


@pytest.fixture(autouse=True)
def _clean_onedrive_env(monkeypatch):
    """No ambient OneDrive credentials leak into any test."""
    for var in _ONEDRIVE_VARS:
        monkeypatch.delenv(var, raising=False)


class _FakeResponse:
    def __init__(self, status_code=200, body=None, content=b"", text=""):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.content = content
        self.text = text or ""

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://graph.microsoft.com/v1.0/x")
            raise httpx.HTTPStatusError(
                f"{self.status_code}",
                request=request,
                response=httpx.Response(self.status_code, request=request),
            )


class _Transport:
    """Records every outbound httpx call and replays scripted responses."""

    def __init__(self):
        self.posts = []
        self.gets = []
        self.post_response = _FakeResponse(200, {"access_token": "graph-access-token-123"})
        self.get_response = _FakeResponse(200, {"value": []})

    def install(self, monkeypatch):
        transport = self

        async def fake_post(self, url, *, data=None, headers=None, **kwargs):
            transport.posts.append({"url": url, "data": data, "headers": headers})
            return transport.post_response

        async def fake_get(self, url, *, headers=None, params=None, **kwargs):
            transport.gets.append({"url": url, "headers": headers, "params": params})
            return transport.get_response

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
        return self


@pytest.fixture
def transport(monkeypatch):
    return _Transport().install(monkeypatch)


def _full_creds(monkeypatch, tenant=None):
    monkeypatch.setenv("ONEDRIVE_CLIENT_ID", "client-abc")
    monkeypatch.setenv("ONEDRIVE_CLIENT_SECRET", "s3cret-value")
    monkeypatch.setenv("ONEDRIVE_REFRESH_TOKEN", "refresh-xyz")
    if tenant:
        monkeypatch.setenv("ONEDRIVE_TENANT_ID", tenant)


# ── The grant ─────────────────────────────────────────────────────────────────


async def test_refresh_grant_posts_the_documented_form_to_the_tenant_endpoint(
    monkeypatch, transport
):
    """The refresh-token grant: exact endpoint, exact form fields, exact scope."""
    _full_creds(monkeypatch, tenant="contoso.onmicrosoft.com")
    transport.get_response = _FakeResponse(200, {"value": []})

    out = await OneDriveBlock().process(None, {"operation": "list"})

    assert len(transport.posts) == 1, "the grant must be requested exactly once"
    grant = transport.posts[0]
    assert grant["url"] == (
        "https://login.microsoftonline.com/contoso.onmicrosoft.com/oauth2/v2.0/token"
    )
    assert grant["data"]["grant_type"] == "refresh_token"
    assert grant["data"]["refresh_token"] == "refresh-xyz"
    assert grant["data"]["client_id"] == "client-abc"
    assert grant["data"]["client_secret"] == "s3cret-value"
    assert grant["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    assert out["status"] == "success"


async def test_grant_requests_least_privilege_scope_only(monkeypatch, transport):
    """Files.Read + offline_access and nothing else: a leaked token cannot write."""
    _full_creds(monkeypatch)

    await OneDriveBlock().process(None, {"operation": "list"})

    scope = transport.posts[0]["data"]["scope"]
    assert scope == "Files.Read offline_access"
    assert "ReadWrite" not in scope
    assert "Files.ReadWrite" not in scope


async def test_grant_defaults_to_the_common_tenant(monkeypatch, transport):
    """With no ONEDRIVE_TENANT_ID the block targets the multi-tenant endpoint."""
    _full_creds(monkeypatch)

    await OneDriveBlock().process(None, {"operation": "list"})

    assert transport.posts[0]["url"] == (
        "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    )


async def test_graph_is_called_with_the_minted_access_token_never_the_refresh_token(
    monkeypatch, transport
):
    """The bearer sent to Graph is the grant response's access_token.

    This is the whole point of the grant: the long-lived refresh token must stay
    at login.microsoftonline.com and never reach graph.microsoft.com.
    """
    _full_creds(monkeypatch)
    transport.post_response = _FakeResponse(200, {"access_token": "minted-AT-999"})

    await OneDriveBlock().process(None, {"operation": "list"})

    assert len(transport.gets) == 1
    sent_headers = transport.gets[0]["headers"]
    assert sent_headers["Authorization"] == "Bearer minted-AT-999"
    assert "refresh-xyz" not in str(sent_headers)
    assert "s3cret-value" not in str(sent_headers)


async def test_failed_refresh_reports_the_provider_status_and_body(monkeypatch, transport):
    """A rejected grant surfaces Microsoft's status code and body, and stops.

    NOTE (finding, not asserted as desirable): the block returns
    status="success" with mode="unconfigured" here, so a *revoked* credential is
    reported the same way as a *missing* one. The assertion below pins the
    observable behaviour of the current code, including that no Graph call is
    attempted once the grant fails.
    """
    _full_creds(monkeypatch)
    transport.post_response = _FakeResponse(
        401, {}, text='{"error":"invalid_grant","error_description":"AADSTS70008"}'
    )

    out = await OneDriveBlock().process(None, {"operation": "list"})

    assert "Token refresh failed (401)" in out["error"]
    assert "invalid_grant" in out["error"]
    assert out["mode"] == "unconfigured"
    assert out["files"] == []
    assert transport.gets == [], "no Graph call may be made without a token"


async def test_direct_access_token_skips_the_grant_entirely(monkeypatch, transport):
    """The ONEDRIVE_ACCESS_TOKEN fallback must not hit the token endpoint."""
    monkeypatch.setenv("ONEDRIVE_ACCESS_TOKEN", "direct-token-9")

    await OneDriveBlock().process(None, {"operation": "list"})

    assert transport.posts == []
    assert transport.gets[0]["headers"]["Authorization"] == "Bearer direct-token-9"


async def test_partial_credentials_fall_through_to_the_unconfigured_refusal(
    monkeypatch, transport
):
    """A refresh token without a client secret is not a usable grant."""
    monkeypatch.setenv("ONEDRIVE_CLIENT_ID", "client-abc")
    monkeypatch.setenv("ONEDRIVE_REFRESH_TOKEN", "refresh-xyz")

    out = await OneDriveBlock().process(None, {"operation": "list"})

    assert transport.posts == []
    assert out["mode"] == "unconfigured"
    assert "No OneDrive credentials configured" in out["error"]
    assert out["auth_url"].startswith(
        "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
    )


# ── Graph requests the block builds ───────────────────────────────────────────


async def test_list_without_query_reads_the_drive_root(monkeypatch, transport):
    monkeypatch.setenv("ONEDRIVE_ACCESS_TOKEN", "direct-token-9")

    await OneDriveBlock().process(None, {"operation": "list", "limit": 5})

    call = transport.gets[0]
    assert call["url"] == "https://graph.microsoft.com/v1.0/me/drive/root/children"
    assert call["params"]["$top"] == 5
    assert call["params"]["$select"] == (
        "id,name,size,lastModifiedDateTime,webUrl,file,folder"
    )


async def test_list_with_query_builds_the_graph_search_clause(monkeypatch, transport):
    monkeypatch.setenv("ONEDRIVE_ACCESS_TOKEN", "direct-token-9")

    await OneDriveBlock().process("budget 2026", {"operation": "list"})

    assert transport.gets[0]["url"] == (
        "https://graph.microsoft.com/v1.0/me/drive/search(q='budget 2026')"
    )


async def test_single_quote_in_query_is_refused_before_any_request(monkeypatch, transport):
    """Graph search uses ' as its literal delimiter: a quote would inject a clause."""
    monkeypatch.setenv("ONEDRIVE_ACCESS_TOKEN", "direct-token-9")

    out = await OneDriveBlock().process("bud') or name eq ('x", {"operation": "list"})

    assert out["status"] == "error"
    assert out["error"] == "Search query may not contain single quotes"
    assert transport.gets == [], "the refusal must precede the Graph call"


async def test_graph_items_are_mapped_to_the_block_file_rows(monkeypatch, transport):
    """Folders, mime types, byte sizes and date truncation are all computed here."""
    monkeypatch.setenv("ONEDRIVE_ACCESS_TOKEN", "direct-token-9")
    transport.get_response = _FakeResponse(
        200,
        {
            "value": [
                {
                    "id": "01FOLDER",
                    "name": "Contracts",
                    "folder": {"childCount": 3},
                    "size": 0,
                    "lastModifiedDateTime": "2026-03-04T11:22:33Z",
                    "webUrl": "https://contoso-my.sharepoint.com/Contracts",
                },
                {
                    "id": "01FILE",
                    "name": "boq.pdf",
                    "file": {"mimeType": "application/pdf"},
                    "size": 204800,
                    "lastModifiedDateTime": "2026-01-15T09:00:00Z",
                    "webUrl": "https://contoso-my.sharepoint.com/boq.pdf",
                },
            ]
        },
    )

    out = await OneDriveBlock().process(None, {"operation": "list"})

    assert out["total"] == 2
    folder, pdf = out["files"]
    assert folder["type"] == "folder"
    assert folder["name"] == "Contracts"
    assert pdf["type"] == "pdf", "mimeType tail is the advertised type"
    assert pdf["size_bytes"] == 204800
    assert pdf["modified"] == "2026-01-15", "timestamp is truncated to the date"
    assert pdf["url"] == "https://contoso-my.sharepoint.com/boq.pdf"


async def test_graph_http_error_is_reported_as_a_list_failure(monkeypatch, transport):
    monkeypatch.setenv("ONEDRIVE_ACCESS_TOKEN", "direct-token-9")
    transport.get_response = _FakeResponse(403, {})

    out = await OneDriveBlock().process(None, {"operation": "list"})

    assert out["status"] == "error"
    assert out["operation"] == "list"
    assert "403" in out["error"]


# ── Download ──────────────────────────────────────────────────────────────────


async def test_download_returns_the_exact_bytes_base64_encoded(monkeypatch, transport):
    monkeypatch.setenv("ONEDRIVE_ACCESS_TOKEN", "direct-token-9")
    raw = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\nbinary-body"
    transport.get_response = _FakeResponse(200, {}, content=raw)

    out = await OneDriveBlock().process("01ITEMID", {"operation": "download"})

    assert transport.gets[0]["url"] == (
        "https://graph.microsoft.com/v1.0/me/drive/items/01ITEMID/content"
    )
    assert out["file_id"] == "01ITEMID"
    assert out["size_bytes"] == len(raw)
    assert base64.b64decode(out["content_base64"]) == raw


async def test_download_without_an_item_id_is_refused(monkeypatch, transport):
    monkeypatch.setenv("ONEDRIVE_ACCESS_TOKEN", "direct-token-9")

    out = await OneDriveBlock().process("", {"operation": "download"})

    assert out["status"] == "error"
    assert out["error"] == "file_id required for download"
    assert transport.gets == []


async def test_download_without_credentials_is_an_error_not_a_mock(monkeypatch, transport):
    out = await OneDriveBlock().process("01ITEMID", {"operation": "download"})

    assert out["status"] == "error"
    assert "No OneDrive credentials configured" in out["error"]


# ── Auth URL / status / dispatch ──────────────────────────────────────────────


async def test_auth_url_carries_client_id_redirect_and_least_privilege_scope(monkeypatch):
    monkeypatch.setenv("ONEDRIVE_CLIENT_ID", "client-abc")
    monkeypatch.setenv("ONEDRIVE_TENANT_ID", "contoso.onmicrosoft.com")
    monkeypatch.setenv("ONEDRIVE_REDIRECT_URI", "https://app.example.com/cb")

    out = await OneDriveBlock().process(None, {"operation": "auth"})

    url = out["auth_url"]
    assert url.startswith(
        "https://login.microsoftonline.com/contoso.onmicrosoft.com/oauth2/v2.0/authorize"
    )
    assert "client_id=client-abc" in url
    assert "redirect_uri=https://app.example.com/cb" in url
    assert "scope=Files.Read%20offline_access" in url
    assert "response_type=code" in url
    assert out["authenticated"] is False
    assert out["credentials_configured"] is True


async def test_auth_reports_authenticated_once_a_refresh_token_exists(monkeypatch):
    _full_creds(monkeypatch)

    out = await OneDriveBlock().process(None, {"operation": "status"})

    assert out["authenticated"] is True
    assert "Credentials are set" in out["instructions"]


async def test_auth_url_is_none_without_a_client_id(monkeypatch):
    out = await OneDriveBlock().process(None, {"operation": "auth"})

    assert out["auth_url"] is None
    assert out["authenticated"] is False
    assert out["credentials_configured"] is False


async def test_unknown_operation_names_the_supported_ones(monkeypatch):
    out = await OneDriveBlock().process(None, {"operation": "delete_everything"})

    assert out["status"] == "error"
    assert out["error"] == (
        "Unknown operation: delete_everything. Use: auth, list, download"
    )


async def test_operation_may_arrive_in_the_input_dict(monkeypatch, transport):
    """Chained callers pass operation inside input_data, not params."""
    monkeypatch.setenv("ONEDRIVE_ACCESS_TOKEN", "direct-token-9")

    out = await OneDriveBlock().process({"operation": "download", "query": "01XYZ"}, {})

    assert out["operation"] == "download"
    assert out["file_id"] == "01XYZ"
