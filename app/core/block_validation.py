"""Block validation gate (Phase 3 of the marketplace security design).

Performs static AST analysis and manifest checks before a block is admitted to
``BLOCK_REGISTRY``. Validation results are persisted in a JSON-backed
``CertificationStore``.

If the ``cryptography`` package is not installed, signature verification is
skipped and the resulting status is ``unverified``/``failed`` with a clear
reason; core blocks are not affected because they are trusted by the platform.
"""

from __future__ import annotations

import ast
import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Set

from app.core.manifest_contract import check_contract_fields
from app.core.trust_tier import check_trust_tier

logger = logging.getLogger(__name__)

STATUS = Literal["passed", "failed", "unverified"]

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DEFAULT_CERTIFICATION_STORE_PATH = DEFAULT_DATA_DIR / "block_certifications.json"

CERTIFICATION_TTL_DAYS = 30

FORBIDDEN_MODULES: Set[str] = {
    "os",
    "subprocess",
    "socket",
    "requests",
    "urllib",
    "pickle",
    "ctypes",
    "sys",
}

FORBIDDEN_BUILTINS: Set[str] = {
    "eval",
    "exec",
    "compile",
    "open",
    "__import__",
}

FORBIDDEN_NAMES: Set[str] = {
    "BLOCK_REGISTRY",
    "block_instances",
    "get_memory_block",
}


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _default_expires_at() -> str:
    """Return the default certification expiration time."""
    return (datetime.now(timezone.utc) + timedelta(days=CERTIFICATION_TTL_DAYS)).isoformat()


def _canonical_json(payload: Any) -> str:
    """Return a deterministic JSON representation of ``payload``."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


try:
    from app.core.publisher_registry import (
        BlockSigner,
        BlockVerifier,
        PublisherRegistry,
    )

    _CRYPTOGRAPHY_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency guard
    BlockVerifier = None  # type: ignore[misc, assignment]
    BlockSigner = None  # type: ignore[misc, assignment]
    PublisherRegistry = None  # type: ignore[misc, assignment]
    _CRYPTOGRAPHY_AVAILABLE = False


@dataclass
class BlockValidationResult:
    """Certification record for a single block validation run."""

    block_id: str
    version: str
    publisher_id: Optional[str]
    status: STATUS
    reasons: List[str] = field(default_factory=list)
    certified_at: str = field(default_factory=_now_iso)
    expires_at: str = field(default_factory=_default_expires_at)
    publisher_tier: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-friendly dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BlockValidationResult":
        """Deserialize from a dict."""
        return cls(**data)


class CertificationStore:
    """Thread-safe JSON-backed store for block validation results.

    Writes are atomic (temp file + rename) and protected by an in-process lock.
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path else DEFAULT_CERTIFICATION_STORE_PATH
        self._lock = threading.Lock()
        self._results: Dict[str, BlockValidationResult] = {}
        self.load()

    def load(self) -> None:
        """Load certifications from disk."""
        with self._lock:
            self._results.clear()
            if not self.path.exists():
                return
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"corrupt certification store: {self.path}") from exc

            for record in data.get("certifications", []):
                try:
                    result = BlockValidationResult.from_dict(record)
                    self._results[result.block_id] = result
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"invalid certification record: {record}") from exc

    def _save_unlocked(self) -> None:
        """Persist the store to disk; caller must hold ``self._lock``."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "updated_at": _now_iso(),
            "certifications": [
                result.to_dict() for result in self._results.values()
            ],
        }
        tmp_path = self.path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp_path, self.path)

    def save(self) -> None:
        """Persist the current store to disk atomically."""
        with self._lock:
            self._save_unlocked()

    def get(self, block_id: str) -> Optional[BlockValidationResult]:
        """Return the certification for ``block_id``, or ``None``."""
        with self._lock:
            return self._results.get(block_id)

    def save_result(self, result: BlockValidationResult) -> None:
        """Persist ``result`` to the store."""
        with self._lock:
            self._results[result.block_id] = result
            self._save_unlocked()

    def is_certified(self, block_id: str) -> bool:
        """Return ``True`` if the block has a non-expired passing certification."""
        result = self.get(block_id)
        if result is None or result.status != "passed":
            return False
        try:
            expires = datetime.fromisoformat(result.expires_at)
        except ValueError:
            return False
        return datetime.now(timezone.utc) < expires


class _ForbiddenNodeVisitor(ast.NodeVisitor):
    """Collect forbidden imports, builtins, and names from a block source AST."""

    def __init__(
        self,
        allowed_imports: Set[str],
    ) -> None:
        self.allowed_imports = allowed_imports
        self.found: List[str] = []

    def _is_forbidden_module(self, name: str) -> bool:
        """Return True if ``name`` or its top-level package is forbidden."""
        top = name.split(".")[0]
        return top in FORBIDDEN_MODULES and top not in self.allowed_imports

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if self._is_forbidden_module(alias.name):
                self.found.append(
                    f"forbidden import '{alias.name}' (not declared in permissions.imports)"
                )
            elif alias.name == "importlib" and "importlib" not in self.allowed_imports:
                self.found.append(
                    "dynamic import via 'importlib' (not declared in permissions.imports)"
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module is None:
            self.generic_visit(node)
            return
        if self._is_forbidden_module(node.module):
            self.found.append(
                f"forbidden import from '{node.module}' (not declared in permissions.imports)"
            )
        elif node.module == "importlib" or node.module.startswith("importlib."):
            if "importlib" not in self.allowed_imports:
                self.found.append(
                    "dynamic import from 'importlib' (not declared in permissions.imports)"
                )
        self.generic_visit(node)

    def _is_forbidden_name(self, name: str) -> bool:
        return name in FORBIDDEN_NAMES

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_BUILTINS:
                self.found.append(f"forbidden builtin call '{node.func.id}'")
            elif self._is_forbidden_name(node.func.id):
                self.found.append(f"forbidden access to '{node.func.id}'")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load) and self._is_forbidden_name(node.id):
            self.found.append(f"forbidden access to '{node.id}'")
        self.generic_visit(node)


class BlockValidator:
    """Static validation gate for third-party blocks."""

    def __init__(
        self,
        publisher_registry: Optional[Any] = None,
        certification_store_path: Optional[Path] = None,
    ) -> None:
        if publisher_registry is not None:
            self.publisher_registry = publisher_registry
        elif _CRYPTOGRAPHY_AVAILABLE and PublisherRegistry is not None:
            self.publisher_registry = PublisherRegistry()
        else:
            self.publisher_registry = None
        self.certification_store = CertificationStore(path=certification_store_path)

    def _load_manifest(self, block_path: Path) -> Dict[str, Any]:
        """Load and return ``block.json`` from ``block_path``."""
        manifest_path = block_path / "block.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"block manifest not found: {manifest_path}")
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    def _check_required_fields(self, manifest: Dict[str, Any]) -> List[str]:
        """Return a list of reasons for missing required manifest fields.

        ``trust_tier`` is a provenance claim (``platform`` /
        ``contributor_reviewed``), not ``publisher_tier``. Values are pinned
        to Factory ``ACCEPTED_TRUST_TIERS`` via ``app.core.trust_tier``.
        """
        reasons: List[str] = []
        required = (
            "id",
            "name",
            "version",
            "publisher_id",
            "signature",
            "digests",
            "permissions",
            "trust_tier",
        )
        for field_name in required:
            if field_name not in manifest or manifest[field_name] in (None, ""):
                reasons.append(f"missing required manifest field: {field_name}")
        if "trust_tier" in manifest and manifest.get("trust_tier") not in (None, ""):
            reasons.extend(check_trust_tier(manifest))
        # Contract fields are optional in this phase; only declared ones are
        # checked. See app/core/manifest_contract.py.
        reasons.extend(check_contract_fields(manifest))
        return reasons

    def _verify_signature(self, block_path: Path, publisher_id: Optional[str]) -> List[str]:
        """Verify publisher signature/integrity; return reasons on failure."""
        if not _CRYPTOGRAPHY_AVAILABLE or BlockVerifier is None:
            return ["cryptography not installed; signature verification unavailable"]

        verifier = BlockVerifier(registry=self.publisher_registry)
        try:
            result = verifier.verify_block(block_path, publisher_id=publisher_id)
        except Exception as exc:
            return [f"signature verification error: {exc}"]

        if not result["verified"]:
            return [result["reason"] or "signature verification failed"]
        return []

    def _scan_ast_path(
        self,
        source_path: Path,
        permissions: Dict[str, Any],
    ) -> List[str]:
        """Run static AST analysis on an arbitrary Python file."""
        try:
            source = source_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(source_path))
        except SyntaxError as exc:
            return [f"{source_path.name} syntax error: {exc}"]
        except Exception as exc:
            return [f"failed to read {source_path.name}: {exc}"]

        declared_imports: Set[str] = set()
        declared = permissions.get("imports")
        if isinstance(declared, list):
            declared_imports.update(declared)

        visitor = _ForbiddenNodeVisitor(allowed_imports=declared_imports)
        visitor.visit(tree)
        return [f"implementation: {reason}" for reason in visitor.found]

    def _scan_ast(
        self,
        block_path: Path,
        permissions: Dict[str, Any],
    ) -> List[str]:
        """Run static AST analysis on ``block.py`` and return reasons."""
        block_py = block_path / "block.py"
        if not block_py.exists():
            return ["block.py not found"]

        return self._scan_ast_path(block_py, permissions)

    def _check_permissions_coherence(
        self, manifest: Dict[str, Any]
    ) -> List[str]:
        """Return reasons if the permissions declaration is incoherent."""
        reasons: List[str] = []
        permissions = manifest.get("permissions")
        if not isinstance(permissions, dict):
            reasons.append("permissions must be a dict")
            return reasons

        for key in ("network", "filesystem"):
            value = permissions.get(key)
            if value is not None and not isinstance(value, (bool, list)):
                reasons.append(f"permissions.{key} must be a bool or list")

        imports = permissions.get("imports")
        if imports is not None and not isinstance(imports, list):
            reasons.append("permissions.imports must be a list")

        blocks = permissions.get("blocks")
        if blocks is not None and not isinstance(blocks, list):
            reasons.append("permissions.blocks must be a list")

        return reasons

    def validate_block(
        self,
        block_path: Path,
        publisher_id: Optional[str] = None,
    ) -> BlockValidationResult:
        """Validate ``block_path`` and return a certification result.

        The result is automatically persisted to the certification store.
        """
        block_path = Path(block_path)
        reasons: List[str] = []
        manifest: Dict[str, Any] = {}

        try:
            manifest = self._load_manifest(block_path)
        except FileNotFoundError as exc:
            reasons.append(str(exc))
        except json.JSONDecodeError as exc:
            reasons.append(f"invalid block.json: {exc}")

        block_id = manifest.get("id") or block_path.name
        version = manifest.get("version") or "0.0.0"
        manifest_publisher = manifest.get("publisher_id")
        resolved_publisher = publisher_id or manifest_publisher

        publisher_tier: Optional[str] = None
        if resolved_publisher and self.publisher_registry is not None:
            record = self.publisher_registry.get(resolved_publisher)
            if record is not None:
                publisher_tier = record.tier
                if record.tier == "revoked":
                    reasons.append(f"publisher revoked: {resolved_publisher}")
            else:
                publisher_tier = "community"
        else:
            publisher_tier = "community"

        if not reasons:
            reasons.extend(self._check_required_fields(manifest))

        if not reasons:
            signature_reasons = self._verify_signature(block_path, publisher_id)
            if signature_reasons:
                reasons.extend(signature_reasons)

        if not reasons:
            permissions = manifest.get("permissions", {})
            reasons.extend(self._check_permissions_coherence(manifest))
            # Scan the registry adapter (block.py) for forbidden imports/names.
            reasons.extend(self._scan_ast(block_path, permissions))

        if reasons:
            status: STATUS = "failed"
        elif not _CRYPTOGRAPHY_AVAILABLE:
            # Manifest/AST passed but we cannot verify the signature.
            status = "unverified"
            reasons.append(
                "cryptography not installed; block treated as unverified"
            )
        else:
            status = "passed"

        result = BlockValidationResult(
            block_id=block_id,
            version=version,
            publisher_id=resolved_publisher,
            status=status,
            reasons=reasons,
            certified_at=_now_iso(),
            expires_at=_default_expires_at(),
            publisher_tier=publisher_tier,
        )
        self.certification_store.save_result(result)
        return result

    def is_certified(self, block_id: str) -> bool:
        """Return ``True`` if ``block_id`` has a current passing certification."""
        return self.certification_store.is_certified(block_id)
