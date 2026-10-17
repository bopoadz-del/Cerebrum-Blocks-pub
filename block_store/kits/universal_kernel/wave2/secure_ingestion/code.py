"""Neutral secure ingestion primitives: validation, magic-byte detection, digests."""

from __future__ import annotations

import hashlib
import mimetypes
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

DEFAULT_SIZE_LIMIT_BYTES = 10 * 1024 * 1024

# Extensions that are never accepted regardless of MIME claims.
BLOCKED_EXTENSIONS: frozenset = frozenset({".exe", ".dll", ".sh", ".bat"})


class IngestionRejected(ValueError):
    """Raised when an ingestion request fails validation."""


@dataclass
class IngestionRequest:
    """Neutral ingestion request."""

    filename: str
    content_bytes: bytes
    claimed_mime: str
    tenant_id: str
    project_id: str
    source_tags: Dict[str, str] = field(default_factory=dict)


@dataclass
class IngestionResult:
    """Neutral ingestion result."""

    ok: bool
    digest: str
    detected_mime: str
    warnings: List[str] = field(default_factory=list)
    honesty: str = "validated"


def _extension(filename: str) -> str:
    """Return the lower-case extension including the dot."""
    return os.path.splitext(filename or "")[1].lower()


def _detect_mime(content_bytes: bytes, filename: str) -> Optional[str]:
    """Detect MIME type from magic bytes; fall back to extension mapping."""
    ext = _extension(filename)

    # PDF
    if content_bytes.startswith(b"%PDF"):
        return "application/pdf"

    # ZIP-based formats (DOCX, XLSX)
    if content_bytes.startswith(b"PK\x03\x04"):
        if ext in {".xlsx", ".xlsm"}:
            return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if ext in {".docx", ".docm"}:
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        return "application/zip"

    # JSON
    if content_bytes.strip().startswith((b"{", b"[")):
        try:
            import json

            json.loads(content_bytes.decode("utf-8", errors="replace"))
            return "application/json"
        except Exception:
            pass

    # Plain text by extension.
    if ext in {".txt", ".text"}:
        return "text/plain"
    if ext in {".md", ".markdown"}:
        return "text/markdown"
    if ext == ".csv":
        return "text/csv"

    # Fallback to stdlib guess.
    guessed, _ = mimetypes.guess_type(filename)
    return guessed


def _extension_matches_mime(filename: str, detected_mime: Optional[str]) -> bool:
    """Return True when the filename extension is consistent with detected MIME."""
    ext = _extension(filename)
    if not ext or not detected_mime:
        return True  # Nothing to contradict.

    mapping = {
        ".txt": {"text/plain"},
        ".md": {"text/markdown", "text/plain"},
        ".csv": {"text/csv", "text/plain"},
        ".json": {"application/json", "text/plain"},
        ".xlsx": {
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/zip",
        },
        ".xlsm": {
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/zip",
        },
        ".pdf": {"application/pdf"},
    }
    allowed = mapping.get(ext)
    if allowed is None:
        return True  # Unknown extension cannot be mismatched.
    return detected_mime in allowed


def _is_blocked_extension(filename: str) -> bool:
    return _extension(filename) in BLOCKED_EXTENSIONS


def validate(
    request: IngestionRequest,
    size_limit: int = DEFAULT_SIZE_LIMIT_BYTES,
    allow_unknown: bool = False,
) -> IngestionResult:
    """Validate an ingestion request; fail closed on any policy violation."""
    warnings: List[str] = []

    if not request.filename:
        raise IngestionRejected("filename is required")
    if request.content_bytes is None:
        raise IngestionRejected("content_bytes is required")

    if _is_blocked_extension(request.filename):
        raise IngestionRejected(
            f"blocked extension for filename {request.filename!r}"
        )

    if len(request.content_bytes) > size_limit:
        raise IngestionRejected(
            f"content size {len(request.content_bytes)} exceeds limit {size_limit}"
        )

    detected_mime = _detect_mime(request.content_bytes, request.filename)

    if detected_mime is None and not allow_unknown:
        raise IngestionRejected("unable to detect content type")

    if detected_mime and not _extension_matches_mime(request.filename, detected_mime):
        warnings.append(
            f"extension/mime mismatch: detected {detected_mime}, "
            f"claimed {request.claimed_mime}"
        )

    digest = hashlib.sha256(request.content_bytes).hexdigest()

    return IngestionResult(
        ok=True,
        digest=digest,
        detected_mime=detected_mime or request.claimed_mime or "application/octet-stream",
        warnings=warnings,
        honesty="validated",
    )
