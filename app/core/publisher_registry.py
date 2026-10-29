"""Publisher identity registry and Ed25519 block signing/verification.

This module implements Phase 1 of the marketplace security design:
- ``PublisherRegistry`` persists trusted publishers in ``data/publishers.json``.
- ``BlockSigner`` signs a block folder's files with a publisher's Ed25519 key.
- ``BlockVerifier`` validates the signature and file integrity of a signed block.

If the ``cryptography`` package is not installed, importing this module raises a
helpful ``ImportError``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Literal, Optional

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )
except ImportError as exc:  # pragma: no cover - dependency guard
    raise ImportError(
        "The publisher registry requires the 'cryptography' package. "
        "Install it with: pip install 'cryptography>=42.0.0'"
    ) from exc


TIER = Literal["community", "reviewed", "certified", "revoked"]

# Tier semantics:
#   community  = sandbox-only execution (default for unknown publishers)
#   reviewed   = may run in-process when capabilities are safe
#   certified  = pilot-proven; may run in-process even with elevated capabilities
#   revoked    = rejected at admission and runtime

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DEFAULT_PUBLISHERS_PATH = DEFAULT_DATA_DIR / "publishers.json"
DEFAULT_PUBLISHERS_KEY_DIR = DEFAULT_DATA_DIR / "publishers"


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(payload: Any) -> str:
    """Return a deterministic JSON representation of ``payload``.

    Uses sorted keys and no whitespace so the same logical payload always
    serializes to the same bytes.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _sha256_file(path: Path) -> str:
    """Return the lowercase hex SHA-256 digest of ``path``'s bytes."""
    hasher = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest().lower()


def _load_private_key(path: Path) -> Ed25519PrivateKey:
    """Load an Ed25519 private key from a PEM file."""
    pem = path.read_bytes()
    key = serialization.load_pem_private_key(pem, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError(f"{path} is not an Ed25519 private key")
    return key


def _load_public_key_base64(b64_key: str) -> Ed25519PublicKey:
    """Load an Ed25519 public key from a base64-encoded string."""
    raw = base64.b64decode(b64_key)
    return Ed25519PublicKey.from_public_bytes(raw)


@dataclass
class PublisherRecord:
    """A single publisher entry in the registry."""

    publisher_id: str
    name: str
    contact: str
    public_key: str
    tier: TIER = "community"
    created_at: str = field(default_factory=_now_iso)
    revoked_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-friendly dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PublisherRecord":
        """Deserialize from a dict."""
        return cls(**data)


class PublisherRegistry:
    """Thread-safe JSON-backed registry of block publishers.

    The registry stores publisher identity records in ``data/publishers.json``.
    Writes are atomic (temp file + rename) and protected by an in-process lock.
    Cross-process locking is not provided; callers should coordinate concurrent
    writes at the deployment level.
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path else DEFAULT_PUBLISHERS_PATH
        self._lock = threading.Lock()
        self._publishers: Dict[str, PublisherRecord] = {}
        self.load()

    def load(self) -> None:
        """Load publishers from disk."""
        with self._lock:
            self._publishers.clear()
            if not self.path.exists():
                return
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"corrupt publisher registry: {self.path}") from exc

            for record in data.get("publishers", []):
                try:
                    pub = PublisherRecord.from_dict(record)
                    self._publishers[pub.publisher_id] = pub
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"invalid publisher record: {record}") from exc

    def _save_unlocked(self) -> None:
        """Persist the registry to disk; caller must hold ``self._lock``."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "updated_at": _now_iso(),
            "publishers": [
                pub.to_dict() for pub in self._publishers.values()
            ],
        }
        tmp_path = self.path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(tmp_path, self.path)

    def save(self) -> None:
        """Persist the current registry to disk atomically."""
        with self._lock:
            self._save_unlocked()

    def register(
        self,
        publisher_id: str,
        name: str,
        contact: str,
        public_key: str,
        tier: TIER = "community",
    ) -> PublisherRecord:
        """Register a new publisher (or update an existing one).

        ``public_key`` must be a base64-encoded Ed25519 public key.
        """
        # Validate key format before storing.
        _load_public_key_base64(public_key)

        with self._lock:
            existing = self._publishers.get(publisher_id)
            record = PublisherRecord(
                publisher_id=publisher_id,
                name=name,
                contact=contact,
                public_key=public_key,
                tier=tier,
                created_at=existing.created_at if existing else _now_iso(),
                revoked_at=None if tier != "revoked" else (existing.revoked_at or _now_iso()),
            )
            self._publishers[publisher_id] = record
            self._save_unlocked()
            return record

    def get(self, publisher_id: str) -> Optional[PublisherRecord]:
        """Return the publisher record, or ``None`` if unknown."""
        with self._lock:
            return self._publishers.get(publisher_id)

    def revoke(self, publisher_id: str) -> Optional[PublisherRecord]:
        """Mark a publisher as revoked and return the updated record."""
        with self._lock:
            record = self._publishers.get(publisher_id)
            if record is None:
                return None
            record.tier = "revoked"
            record.revoked_at = _now_iso()
            self._save_unlocked()
            return record

    def publisher_ids(self) -> list[str]:
        """Return the sorted ids of every registered publisher."""
        with self._lock:
            return sorted(self._publishers)

    def is_trusted(self, publisher_id: str) -> bool:
        """Return ``True`` if the publisher exists and is not revoked."""
        record = self.get(publisher_id)
        if record is None:
            return False
        return record.tier != "revoked"


class BlockSigner:
    """Sign a block folder with an Ed25519 private key."""

    SIGNED_FILES = ("block.json", "block.py", "requirements.txt", "Dockerfile")

    @staticmethod
    def _compute_digests(
        block_path: Path,
        manifest: Optional[Dict[str, Any]] = None,
        normalize_eol: Optional[str] = None,
    ) -> Dict[str, str]:
        """Compute SHA-256 digests of the files covered by the signature.

        ``block.json`` is canonicalized by stripping ``signature`` and
        ``digests`` -- the outputs of signing -- and nothing else: every
        declared field (trust tier, contract, brief scope, verticals) is
        inside the signature, so none can be edited without re-signing. If
        ``manifest`` is supplied, it is used instead of reading
        ``block.json`` from disk (useful during signing before the manifest
        has been persisted).

        ``normalize_eol`` (``'\\n'`` or ``'\\r\\n'``) makes the digest
        calculation independent of the checkout's line endings. This is
        required because signatures produced on a Windows CRLF checkout must
        still verify on a Linux LF checkout, and vice versa.
        """
        digests: Dict[str, str] = {}

        if manifest is None:
            manifest_path = block_path / "block.json"
            if manifest_path.exists():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        if manifest is not None:
            manifest = dict(manifest)
            manifest.pop("signature", None)
            manifest.pop("digests", None)
            canonical = _canonical_json(manifest).encode("utf-8")
            digests["block.json"] = hashlib.sha256(canonical).hexdigest().lower()

        for filename in BlockSigner.SIGNED_FILES:
            if filename == "block.json":
                continue
            file_path = block_path / filename
            if not file_path.exists():
                continue
            data = file_path.read_bytes()
            if normalize_eol is not None:
                # Normalize any line-ending convention to the target convention.
                data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
                data = data.replace(b"\n", normalize_eol.encode("utf-8"))
            digests[filename] = hashlib.sha256(data).hexdigest().lower()

        return digests

    @staticmethod
    def sign_block(
        block_path: Path,
        publisher_id: str,
        private_key: Ed25519PrivateKey,
    ) -> Dict[str, Any]:
        """Sign ``block_path`` and persist ``signature``/``digests`` to ``block.json``.

        Returns a dict with ``publisher_id``, ``digests``, ``signature`` (base64),
        and the canonical ``payload`` string that was signed.
        """
        block_path = Path(block_path)
        manifest_path = block_path / "block.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"block manifest not found: {manifest_path}")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["publisher_id"] = publisher_id

        # Canonical LF digests: signatures are line-ending independent by
        # construction, not by verifier guesswork.
        digests = BlockSigner._compute_digests(
            block_path, manifest=manifest, normalize_eol="\n"
        )

        payload = {"publisher_id": publisher_id, "digests": digests}
        payload_str = _canonical_json(payload)
        signature = private_key.sign(payload_str.encode("utf-8"))

        manifest["digests"] = digests
        manifest["signature"] = base64.b64encode(signature).decode("ascii")

        # LF on every platform: a signed manifest's bytes must not depend on
        # the machine that signed it (a Windows text-mode write produced CRLF
        # copies that kit bundles, which carry no eol attribute, kept).
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )

        return {
            "publisher_id": publisher_id,
            "digests": digests,
            "signature": manifest["signature"],
            "payload": payload_str,
        }


class BlockVerifier:
    """Verify the publisher signature and file integrity of a signed block."""

    def __init__(self, registry: Optional[PublisherRegistry] = None) -> None:
        self.registry = registry or PublisherRegistry()

    def verify_block(self, block_path: Path, publisher_id: Optional[str] = None) -> Dict[str, Any]:
        """Verify a block folder's signature and digests.

        If ``publisher_id`` is supplied, it must match the manifest. If omitted,
        the manifest's own ``publisher_id`` is used.

        Returns a dict with ``verified`` (bool, signature-verification result),
        ``publisher_id``, and ``reason``. ``verified`` here means the signature
        and digests are valid; it is unrelated to the publisher's trust tier.
        """
        block_path = Path(block_path)
        manifest_path = block_path / "block.json"
        if not manifest_path.exists():
            return {
                "verified": False,
                "publisher_id": publisher_id,
                "reason": "block.json not found",
            }

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return {
                "verified": False,
                "publisher_id": publisher_id,
                "reason": f"invalid block.json: {exc}",
            }

        for required in ("publisher_id", "signature", "digests"):
            if required not in manifest:
                return {
                    "verified": False,
                    "publisher_id": publisher_id,
                    "reason": f"missing required field: {required}",
                }

        manifest_publisher = manifest["publisher_id"]
        if publisher_id and publisher_id != manifest_publisher:
            return {
                "verified": False,
                "publisher_id": manifest_publisher,
                "reason": f"publisher mismatch: expected {publisher_id}, got {manifest_publisher}",
            }
        publisher_id = manifest_publisher

        record = self.registry.get(publisher_id)
        if record is None:
            return {
                "verified": False,
                "publisher_id": publisher_id,
                "reason": f"unknown publisher: {publisher_id}",
            }
        if record.tier == "revoked":
            return {
                "verified": False,
                "publisher_id": publisher_id,
                "reason": f"publisher revoked: {publisher_id}",
            }

        # Verify file digests.
        stored_digests: Dict[str, str] = manifest["digests"]
        # Canonical form first (LF-normalized, matching sign_block); legacy
        # raw and CRLF forms accepted for blocks signed before normalization.
        computed_digests = BlockSigner._compute_digests(block_path, normalize_eol="\n")
        digests_match = computed_digests == stored_digests
        if not digests_match:
            for legacy in (None, "\r\n"):
                normalized = BlockSigner._compute_digests(
                    block_path, normalize_eol=legacy
                )
                if normalized == stored_digests:
                    digests_match = True
                    break

        if not digests_match:
            mismatches = []
            for name in set(stored_digests) | set(computed_digests):
                if stored_digests.get(name) != computed_digests.get(name):
                    mismatches.append(name)
            return {
                "verified": False,
                "publisher_id": publisher_id,
                "reason": f"digest mismatch: {sorted(mismatches)}",
            }

        # Verify signature.
        payload = {"publisher_id": publisher_id, "digests": stored_digests}
        payload_str = _canonical_json(payload)
        try:
            public_key = _load_public_key_base64(record.public_key)
            public_key.verify(
                base64.b64decode(manifest["signature"]),
                payload_str.encode("utf-8"),
            )
        except InvalidSignature:
            return {
                "verified": False,
                "publisher_id": publisher_id,
                "reason": "signature verification failed",
            }
        except Exception as exc:  # pragma: no cover - defensive
            return {
                "verified": False,
                "publisher_id": publisher_id,
                "reason": f"signature error: {exc}",
            }

        return {
            "verified": True,
            "publisher_id": publisher_id,
            "reason": None,
        }
