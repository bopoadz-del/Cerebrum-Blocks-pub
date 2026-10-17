"""Tests for the neutral secure ingestion sub-kit."""

import pytest

from block_store.kits.universal_kernel.wave2.secure_ingestion import (
    IngestionRejected,
    IngestionRequest,
    validate,
)


def _req(filename: str, content: bytes, mime: str = "application/octet-stream") -> IngestionRequest:
    return IngestionRequest(
        filename=filename,
        content_bytes=content,
        claimed_mime=mime,
        tenant_id="tenant-1",
        project_id="project-1",
        source_tags={},
    )


def test_valid_text_file_passes():
    req = _req("notes.txt", b"hello world", "text/plain")
    result = validate(req)
    assert result.ok is True
    assert result.detected_mime == "text/plain"
    assert result.digest == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"


def test_blocked_extension_is_rejected():
    req = _req("script.sh", b"echo hi", "text/x-sh")
    with pytest.raises(IngestionRejected):
        validate(req)


def test_oversized_content_is_rejected():
    req = _req("big.txt", b"x" * 11, "text/plain")
    with pytest.raises(IngestionRejected):
        validate(req, size_limit=10)


def test_unknown_type_rejected_by_default():
    req = _req("data.unknown", b"\x00\x01\x02\x03", "application/octet-stream")
    with pytest.raises(IngestionRejected):
        validate(req)


def test_unknown_type_allowed_when_configured():
    req = _req("data.unknown", b"\x00\x01\x02\x03", "application/octet-stream")
    result = validate(req, allow_unknown=True)
    assert result.ok is True
    assert result.detected_mime == "application/octet-stream"


def test_extension_mime_mismatch_warns():
    req = _req("report.txt", b"%PDF-1.4 fake", "text/plain")
    result = validate(req)
    assert result.ok is True
    assert len(result.warnings) == 1
    assert "mismatch" in result.warnings[0]


def test_json_detection():
    req = _req("config.json", b'{"a": 1}', "application/json")
    result = validate(req)
    assert result.detected_mime == "application/json"
