"""Tests for UTF-8 output hardening on Windows cp1252 terminals."""

from __future__ import annotations

import sys

import pytest

from cerebrum_cli import _encoding


@pytest.mark.skipif(sys.platform != "win32", reason="reconfigure is most relevant on Windows")
def test_ensure_utf8_output_reconfigures_streams_on_windows():
    """On Windows, ``ensure_utf8_output`` should set UTF-8 with replace errors."""
    _encoding.ensure_utf8_output()
    assert sys.stdout.encoding.lower() == "utf-8"
    assert sys.stderr.encoding.lower() == "utf-8"
    # ``errors`` may not be exposed on all Python builds, so only assert when present.
    if hasattr(sys.stdout, "errors"):
        assert sys.stdout.errors == "replace"
    if hasattr(sys.stderr, "errors"):
        assert sys.stderr.errors == "replace"


def test_non_ascii_print_does_not_raise():
    """Printing box-drawing and document-like characters should not crash."""
    _encoding.ensure_utf8_output()
    # This text mixes common box-drawing symbols and non-Latin characters that
    # would fail on a cp1252 terminal without the reconfigure step.
    text = "┌─ Summary ─┐ 日本語 test • emoji 🚀"
    print(text, file=sys.stdout)
    print(text, file=sys.stderr)
