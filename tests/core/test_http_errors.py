"""A block failure maps to HTTP by its TYPED kind, never by its message."""

from __future__ import annotations

import asyncio

import httpx

from app.core.http_errors import (
    INPUT,
    UNAVAILABLE,
    BlockUnavailable,
    classify_block_error,
    error_from,
    error_kind,
    mark_unavailable,
    unavailable,
)
from app.core.universal_base import UniversalBlock


def test_words_in_a_message_decide_nothing():
    # The phrases the old classifier matched now carry no meaning on their own.
    assert classify_block_error("Stripe not configured") == 422
    assert classify_block_error({"status": "error", "error": "rate limit; dns; ssl"}) == 422


def test_the_kind_decides():
    assert classify_block_error(unavailable("anything at all")) == 503
    assert classify_block_error({"status": "error", "error": "x", "error_kind": INPUT}) == 422
    assert classify_block_error({"status": "error", "result": {"error": "x", "error_kind": UNAVAILABLE}}) == 503


def test_exceptions_carry_their_kind_by_type_or_mark():
    assert error_kind(BlockUnavailable("x")) == UNAVAILABLE
    # A real client failure: nothing listens on port 1, and httpx raises its
    # own type FROM the socket error -- found through the cause chain.
    try:
        httpx.get("http://127.0.0.1:1", timeout=2)
    except httpx.HTTPError as exc:
        assert error_kind(exc) == UNAVAILABLE
    try:
        raise RuntimeError("wrapper") from ConnectionRefusedError()
    except RuntimeError as exc:
        assert error_kind(exc) == UNAVAILABLE
    assert error_kind(TimeoutError()) == UNAVAILABLE
    assert error_kind(ValueError("not configured")) == INPUT
    marked = mark_unavailable(ValueError("zorblat endpoint missing"))
    assert isinstance(marked, ValueError) and error_kind(marked) == UNAVAILABLE
    assert classify_block_error(marked) == 503
    assert error_from(marked)["error_kind"] == UNAVAILABLE


def test_the_shared_block_base_keeps_the_kind_of_what_it_caught():
    class _Down(UniversalBlock):
        name = "zorblat_down"
        version = "1.0"
        description = "raises a connection failure"

        async def process(self, input_data, params=None):
            raise RuntimeError("provider unreachable") from ConnectionRefusedError()

    envelope = asyncio.run(_Down().execute({}, {}))
    assert envelope["status"] == "error"
    assert classify_block_error(envelope) == 503
