"""SSRF guard is wired into the caller-URL sinks, not just defined.

The audit found ``url_guard.validate_public_url`` existed but the notification
webhook and the PDF/OCR/image blocks fetched caller URLs with
``follow_redirects=True`` and no guard — so a caller could reach
169.254.169.254 (cloud metadata), localhost, or private hosts, directly or via
a redirect. These tests pin the guard behavior and that the webhook rejects
unsafe URLs.
"""

from __future__ import annotations

import pytest

from app.core.url_guard import validate_public_url, UnsafeURLError


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://localhost:8000/admin",
        "http://127.0.0.1/",
        "http://10.0.0.5/internal",
        "http://192.168.1.1/",
        "http://[::1]/",
        "file:///etc/passwd",
        "gopher://127.0.0.1:6379/_",
        "ftp://10.0.0.1/",
        "",
    ],
)
def test_validate_public_url_rejects_unsafe(url):
    with pytest.raises(UnsafeURLError):
        validate_public_url(url)


def test_validate_public_url_allows_public_host():
    # example.com resolves to a public address.
    assert validate_public_url("https://example.com/doc.pdf") == "https://example.com/doc.pdf"


@pytest.mark.asyncio
async def test_notification_webhook_rejects_unsafe_url():
    from app.blocks.notification import NotificationBlock

    block = NotificationBlock()
    result = await block._send_webhook(
        {"url": "http://169.254.169.254/latest/meta-data/", "message": "x", "method": "GET"}
    )
    assert result["status"] == "error"
    assert "unsafe" in result["error"].lower()


def test_caller_url_blocks_disable_redirects():
    # follow_redirects=True on a caller URL allows a public->private redirect
    # bypass. None of the document/image fetchers may keep it enabled.
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2] / "app" / "blocks"
    offenders = []
    for name in ("image", "marker", "ocr", "ocr_v2", "pdf", "pdf_v2"):
        text = (root / f"{name}.py").read_text(encoding="utf-8")
        if "follow_redirects=True" in text:
            offenders.append(name)
    assert not offenders, f"caller-URL fetch still follows redirects (SSRF bypass): {offenders}"
