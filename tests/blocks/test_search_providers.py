"""Search block: the request each provider builds and the rows it parses back.

Offline. The Serper path runs against a faked `httpx.AsyncClient.post`; the
DuckDuckGo path against a fake `ddgs.DDGS`. Both record what the block sent and
hand back a scripted provider response the block then has to normalise.

tests/blocks/test_search.py only drives provider="mock" and asserts the
UniversalBlock envelope, so it never reaches provider selection, the result
normaliser, or the num_results cap. Each assertion below names something
SearchBlock.process computed: the endpoint and API-key header, the request body,
the display_url it derived with urlparse, the provider it selected, and the
refusal text for an empty query.
"""

from __future__ import annotations

import httpx
import pytest

from app.blocks.search import SearchBlock


@pytest.fixture(autouse=True)
def _no_ambient_serper_key(monkeypatch):
    monkeypatch.delenv("SERPER_API_KEY", raising=False)


class _SerperTransport:
    def __init__(self, body=None):
        self.calls = []
        self.body = body if body is not None else {"organic": []}

    def install(self, monkeypatch):
        transport = self

        async def fake_post(self, url, *, headers=None, json=None, **kwargs):
            transport.calls.append({"url": url, "headers": headers, "json": json})
            request = httpx.Request("POST", url)
            return httpx.Response(200, json=transport.body, request=request)

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        return self


class _FakeDDGS:
    """Stands in for ddgs.DDGS: a context manager with a .text() method."""

    calls = []
    rows = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def text(self, query, max_results=None):
        type(self).calls.append({"query": query, "max_results": max_results})
        return list(type(self).rows)


@pytest.fixture
def fake_ddgs(monkeypatch):
    import ddgs

    _FakeDDGS.calls = []
    _FakeDDGS.rows = []
    monkeypatch.setattr(ddgs, "DDGS", _FakeDDGS)
    return _FakeDDGS


# -- Refusals ------------------------------------------------------------------


async def test_empty_query_is_refused():
    out = await SearchBlock().process("", {})

    assert out["status"] == "error"
    assert out["error"] == "Query is required"


async def test_whitespace_only_query_is_refused():
    out = await SearchBlock().process("   \t ", {})

    assert out["status"] == "error"
    assert out["error"] == "Query is required"


# -- Mock provider -------------------------------------------------------------


async def test_mock_provider_echoes_the_query_and_returns_one_offline_row():
    out = await SearchBlock().process("python programming", {"provider": "mock"})

    assert out["query"] == "python programming"
    assert out["provider"] == "mock"
    assert out["total"] == 1
    row = out["results"][0]
    assert row["url"] == "https://example.com/mock"
    assert row["display_url"] == "example.com"
    assert row["source"] == "mock"


async def test_mock_provider_short_circuits_before_any_network(monkeypatch, fake_ddgs):
    """provider=mock must not reach a provider even when one is configured."""
    transport = _SerperTransport().install(monkeypatch)
    monkeypatch.setenv("SERPER_API_KEY", "should-not-be-used")

    out = await SearchBlock().process("anything", {"provider": "mock"})

    assert out["provider"] == "mock"
    assert transport.calls == []
    assert fake_ddgs.calls == []


# -- Serper --------------------------------------------------------------------


async def test_serper_request_carries_the_api_key_header_and_query_body(monkeypatch):
    transport = _SerperTransport({"organic": []}).install(monkeypatch)
    monkeypatch.setenv("SERPER_API_KEY", "serper-key-42")

    await SearchBlock().process("bill of quantities", {"num_results": 3})

    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["url"] == "https://google.serper.dev/search"
    assert call["headers"]["X-API-KEY"] == "serper-key-42"
    assert call["headers"]["Content-Type"] == "application/json"
    assert call["json"] == {"q": "bill of quantities", "num": 3}


async def test_serper_rows_are_normalised_with_a_derived_display_url(monkeypatch):
    _SerperTransport(
        {
            "organic": [
                {
                    "title": "RICS NRM2",
                    "link": "https://www.rics.org/standards/nrm2?ref=x",
                    "snippet": "Detailed measurement for building works.",
                    "position": 1,
                },
                {
                    "title": "CESMM4",
                    "link": "https://ice.org.uk/cesmm4",
                    "snippet": "Civil engineering standard method.",
                    "position": 2,
                },
            ]
        }
    ).install(monkeypatch)
    monkeypatch.setenv("SERPER_API_KEY", "serper-key-42")

    out = await SearchBlock().process("measurement standards", {})

    assert out["provider"] == "serper"
    assert out["total"] == 2
    first, second = out["results"]
    assert first["url"] == "https://www.rics.org/standards/nrm2?ref=x"
    assert first["display_url"] == "www.rics.org", "netloc is parsed off the link"
    assert first["snippet"] == "Detailed measurement for building works."
    assert first["position"] == 1
    assert first["source"] == "serper"
    assert second["display_url"] == "ice.org.uk"


async def test_num_results_is_capped_at_twenty(monkeypatch):
    transport = _SerperTransport().install(monkeypatch)
    monkeypatch.setenv("SERPER_API_KEY", "serper-key-42")

    await SearchBlock().process("anything", {"num_results": 500})

    assert transport.calls[0]["json"]["num"] == 20


async def test_serper_rows_are_truncated_to_the_requested_count(monkeypatch):
    _SerperTransport(
        {"organic": [{"title": f"r{i}", "link": f"https://e{i}.com/"} for i in range(5)]}
    ).install(monkeypatch)
    monkeypatch.setenv("SERPER_API_KEY", "serper-key-42")

    out = await SearchBlock().process("anything", {"num_results": 2})

    assert out["total"] == 2
    assert [r["title"] for r in out["results"]] == ["r0", "r1"]


async def test_serper_timeout_is_reported_as_a_search_timeout(monkeypatch):
    async def fake_post(self, url, **kwargs):
        raise httpx.TimeoutException("slow")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setenv("SERPER_API_KEY", "serper-key-42")

    out = await SearchBlock().process("anything", {})

    assert out["status"] == "error"
    assert out["error"] == "Search timed out"


async def test_serper_failure_names_the_provider_that_failed(monkeypatch):
    async def fake_post(self, url, **kwargs):
        raise RuntimeError("serper exploded")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setenv("SERPER_API_KEY", "serper-key-42")

    out = await SearchBlock().process("anything", {})

    assert out["status"] == "error"
    assert out["provider"] == "serper"
    assert "serper exploded" in out["error"]


# -- DuckDuckGo ----------------------------------------------------------------


async def test_duckduckgo_is_selected_when_no_api_key_is_set(fake_ddgs):
    fake_ddgs.rows = [
        {
            "title": "Python docs",
            "href": "https://docs.python.org/3/library/asyncio.html",
            "body": "asyncio is a library to write concurrent code.",
        }
    ]

    out = await SearchBlock().process("  asyncio  ", {"num_results": 4})

    assert out["provider"] == "duckduckgo"
    assert fake_ddgs.calls == [{"query": "asyncio", "max_results": 4}], (
        "the query is stripped before it reaches the provider"
    )
    row = out["results"][0]
    assert row["url"] == "https://docs.python.org/3/library/asyncio.html"
    assert row["display_url"] == "docs.python.org"
    assert row["snippet"] == "asyncio is a library to write concurrent code."
    assert row["source"] == "duckduckgo"
    assert out["total"] == 1


async def test_duckduckgo_failure_names_the_provider(fake_ddgs, monkeypatch):
    def boom(self, query, max_results=None):
        raise RuntimeError("rate limited")

    monkeypatch.setattr(_FakeDDGS, "text", boom)

    out = await SearchBlock().process("anything", {})

    assert out["status"] == "error"
    assert out["provider"] == "duckduckgo"
    assert "rate limited" in out["error"]


# -- Input shapes --------------------------------------------------------------


async def test_query_may_arrive_in_a_dict_under_query_text_or_input(fake_ddgs):
    fake_ddgs.rows = []

    for key in ("query", "text", "input"):
        fake_ddgs.calls.clear()
        out = await SearchBlock().process({key: f"via-{key}"}, {})
        assert out["query"] == f"via-{key}"
        assert fake_ddgs.calls[0]["query"] == f"via-{key}"


async def test_params_query_is_used_when_the_input_is_not_a_string_or_dict(fake_ddgs):
    fake_ddgs.rows = []

    out = await SearchBlock().process(None, {"query": "from params"})

    assert out["query"] == "from params"
    assert fake_ddgs.calls[0]["query"] == "from params"
