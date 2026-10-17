"""Web block: the SSRF guard, the redirect chain, and the HTML it actually parses.

Offline throughout. `socket.getaddrinfo` is stubbed with a fixed host table so
app.core.url_guard.validate_public_url runs its real logic against known
addresses, and `httpx.AsyncClient.get` is replaced with a scripted transport
that hands back real `httpx.Response` objects. Nothing resolves or dials out.

tests/blocks/test_web.py asserts only the UniversalBlock envelope keys and
drives the provider="mock" short-circuit, so nothing there touches the parser
or the guard. Every assertion below names a value WebBlock.process computed:
the refusal string for a scheme or a private address, the title/description it
pulled out of the markup, the absolute URL it built from a relative href, the
word count, and the hop it refused to follow.
"""

from __future__ import annotations

import socket

import httpx
import pytest

from app.blocks.web import WebBlock

# Host table used instead of DNS. "internal.example.com" is the attacker's
# trick: a public-looking name that resolves into RFC1918 space.
_HOSTS = {
    "example.com": "93.184.216.34",
    "cdn.example.org": "93.184.216.35",
    "internal.example.com": "10.0.0.5",
    "metadata.example.net": "169.254.169.254",
}


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch):
    def fake_getaddrinfo(host, port, *args, **kwargs):
        if host in _HOSTS:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (_HOSTS[host], port))]
        raise socket.gaierror(f"offline test: unknown host {host!r}")

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


class _Transport:
    """Scripted httpx GETs. Each entry is (status, headers, body)."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def install(self, monkeypatch):
        transport = self

        async def fake_get(self, url, **kwargs):
            transport.calls.append(str(url))
            status, headers, body = (
                transport.script[min(len(transport.calls) - 1, len(transport.script) - 1)]
            )
            request = httpx.Request("GET", url)
            if isinstance(body, bytes):
                return httpx.Response(status, headers=headers, content=body, request=request)
            return httpx.Response(status, headers=headers, text=body, request=request)

        monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
        return self


_PAGE = """<!doctype html>
<html><head>
<title>  Cerebrum Store  </title>
<meta name="description" content="Certified blocks, honestly tested.">
<style>.hidden{display:none}</style>
</head><body>
<nav><a href="/nav-should-be-dropped">nav link</a></nav>
<script>tracker('pageview')</script>
<h1>Blocks</h1>
<p>Three bars decide certification.</p>
<a href="/docs/guide">Guide</a>
<a href="https://cdn.example.org/asset.js">Asset</a>
<a href="/docs/guide">Guide again</a>
<footer>copyright noise</footer>
<noscript>enable javascript</noscript>
</body></html>
"""

_HTML_HEADERS = {"content-type": "text/html; charset=utf-8"}


# -- SSRF guard ---------------------------------------------------------------


async def test_non_http_scheme_is_refused_by_name():
    out = await WebBlock().process("file:///etc/passwd", {})

    assert out["status"] == "error"
    assert out["error"] == "Only http/https URLs are allowed (got 'file')"


async def test_host_resolving_to_a_private_address_is_refused():
    out = await WebBlock().process("http://internal.example.com/admin", {})

    assert out["status"] == "error"
    assert "internal.example.com" in out["error"]
    assert "non-public address (10.0.0.5)" in out["error"]


async def test_link_local_metadata_host_is_refused():
    out = await WebBlock().process("http://metadata.example.net/latest/meta-data/", {})

    assert out["status"] == "error"
    assert "169.254.169.254" in out["error"]


async def test_empty_url_is_refused():
    out = await WebBlock().process("", {})

    assert out["status"] == "error"
    assert out["error"] == "A URL is required"


# -- Parsing ------------------------------------------------------------------


async def test_fetch_extracts_title_description_text_and_absolute_links(monkeypatch):
    transport = _Transport([(200, _HTML_HEADERS, _PAGE)]).install(monkeypatch)

    out = await WebBlock().process("https://example.com/", {})

    assert out["title"] == "Cerebrum Store", "title is stripped of its whitespace"
    assert out["description"] == "Certified blocks, honestly tested."
    assert out["status_code"] == 200
    assert "Three bars decide certification." in out["text"]
    # script/style/nav/footer/noscript are decomposed before text extraction.
    assert "tracker" not in out["text"]
    assert "display:none" not in out["text"]
    assert "nav link" not in out["text"]
    assert "copyright noise" not in out["text"]
    assert "enable javascript" not in out["text"]
    assert out["word_count"] == len(out["text"].split())
    urls = [link["url"] for link in out["links"]]
    # _clean_text() decomposes <nav> before _extract_links() walks the soup, so
    # on the fetch path the nav href is gone and the duplicate /docs/guide is
    # collapsed. (extract_links skips _clean_text and therefore keeps 3 - see
    # test_extract_links_operation_returns_links_without_the_body_text.)
    assert urls == [
        "https://example.com/docs/guide",
        "https://cdn.example.org/asset.js",
    ], "relative hrefs are resolved against the final URL and de-duplicated"
    assert out["links"][0]["text"] == "Guide"
    assert transport.calls == ["https://example.com/"]


async def test_extract_links_operation_returns_links_without_the_body_text(monkeypatch):
    _Transport([(200, _HTML_HEADERS, _PAGE)]).install(monkeypatch)

    out = await WebBlock().process(
        "https://example.com/", {"operation": "extract_links"}
    )

    assert "text" not in out, "extract_links must not carry the page body"
    assert "word_count" not in out
    assert out["title"] == "Cerebrum Store"
    # No _clean_text() on this path, so <nav> survives and its href is listed.
    assert [link["url"] for link in out["links"]] == [
        "https://example.com/nav-should-be-dropped",
        "https://example.com/docs/guide",
        "https://cdn.example.org/asset.js",
    ]


async def test_extract_text_operation_drops_the_link_list(monkeypatch):
    _Transport([(200, _HTML_HEADERS, _PAGE)]).install(monkeypatch)

    out = await WebBlock().process(
        "https://example.com/", {"operation": "extract_text"}
    )

    assert out["links"] == []
    assert "Three bars decide certification." in out["text"]


async def test_og_property_is_used_when_the_meta_name_is_absent(monkeypatch):
    page = (
        '<html><head><meta property="og:description" content="from opengraph">'
        "</head><body><p>body</p></body></html>"
    )
    _Transport([(200, _HTML_HEADERS, page)]).install(monkeypatch)

    out = await WebBlock().process("https://example.com/", {})

    assert out["description"] == "from opengraph"
    assert out["title"] == "", "no <title> and no og:title means an empty title"


async def test_url_may_arrive_inside_a_dict_input(monkeypatch):
    _Transport([(200, _HTML_HEADERS, _PAGE)]).install(monkeypatch)

    out = await WebBlock().process({"url": "https://example.com/"}, {})

    assert out["title"] == "Cerebrum Store"


# -- Redirects ----------------------------------------------------------------


async def test_public_redirect_is_followed_and_the_final_url_is_reported(monkeypatch):
    transport = _Transport(
        [
            (302, {"location": "/final"}, ""),
            (200, _HTML_HEADERS, _PAGE),
        ]
    ).install(monkeypatch)

    out = await WebBlock().process("https://example.com/start", {})

    assert transport.calls == ["https://example.com/start", "https://example.com/final"]
    assert out["url"] == "https://example.com/final"
    assert out["title"] == "Cerebrum Store"


async def test_redirect_into_a_private_host_is_refused_mid_chain(monkeypatch):
    """A public entry URL must not be able to bounce the fetch onto an internal host."""
    transport = _Transport(
        [(302, {"location": "http://internal.example.com/secrets"}, "")]
    ).install(monkeypatch)

    out = await WebBlock().process("https://example.com/start", {})

    assert out["status"] == "error"
    assert out["error"].startswith("Unsafe redirect:")
    assert "10.0.0.5" in out["error"]
    assert transport.calls == ["https://example.com/start"], "the hop is never taken"


async def test_redirect_loop_is_capped(monkeypatch):
    transport = _Transport([(302, {"location": "/again"}, "")]).install(monkeypatch)

    out = await WebBlock().process("https://example.com/loop", {})

    assert out["status"] == "error"
    assert out["error"] == "Too many redirects: https://example.com/loop"
    assert len(transport.calls) == 6, "one initial GET plus the five allowed hops"


# -- Non-HTML and failures -----------------------------------------------------


async def test_binary_content_type_is_summarised_not_parsed(monkeypatch):
    _Transport(
        [(200, {"content-type": "application/pdf"}, b"%PDF-1.7\n12345")]
    ).install(monkeypatch)

    out = await WebBlock().process("https://example.com/doc.pdf", {})

    assert out["content_type"] == "application/pdf"
    assert out["text"] == "[Binary content — 14 bytes]"
    assert out["links"] == []
    assert out["title"] == ""


async def test_http_error_status_is_reported_with_the_url(monkeypatch):
    _Transport([(404, {"content-type": "text/html"}, "nope")]).install(monkeypatch)

    out = await WebBlock().process("https://example.com/missing", {})

    assert out["status"] == "error"
    assert out["error"] == "HTTP 404: https://example.com/missing"


async def test_timeout_is_reported_against_the_requested_url(monkeypatch):
    async def fake_get(self, url, **kwargs):
        raise httpx.TimeoutException("too slow")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    out = await WebBlock().process("https://example.com/slow", {})

    assert out["status"] == "error"
    assert out["error"] == "Timeout fetching https://example.com/slow"
