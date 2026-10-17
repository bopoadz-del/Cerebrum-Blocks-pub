"""Neutral identity primitives: principal registry, bcrypt passwords, JWT tokens."""

from __future__ import annotations

import os
import re
import secrets
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import bcrypt
import jwt

PASSWORD_MIN_LENGTH = 8
DEFAULT_TOKEN_TTL_SECONDS = 3600
ALGORITHM = "HS256"


class KernelConfigurationError(Exception):
    """Raised when a required runtime secret/configuration is missing."""


class WeakPasswordError(ValueError):
    """Raised when a password does not meet the minimum strength policy."""


class UnknownPrincipalError(ValueError):
    """Raised when a principal cannot be resolved or authentication fails."""


class TokenExpiredError(ValueError):
    """Raised when a token has expired or cannot be verified."""


@dataclass
class Principal:
    """Neutral principal record."""

    id: str
    tenant_ids: List[str] = field(default_factory=list)
    project_ids: List[str] = field(default_factory=list)
    roles: List[str] = field(default_factory=list)
    email: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _validate_password(password: str) -> None:
    """Fail-closed password strength check."""
    if not password or len(password) < PASSWORD_MIN_LENGTH:
        raise WeakPasswordError(f"password must be at least {PASSWORD_MIN_LENGTH} characters")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise WeakPasswordError("password must contain at least one letter and one digit")


def _hash_password(password: str) -> str:
    """Hash a password with bcrypt and return an ascii string."""
    pw = password.encode("utf-8")
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("ascii")


def _verify_password(password: str, password_hash: str) -> bool:
    """Check a password against a stored bcrypt hash."""
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        return False


def _resolve_secret(secret: Optional[str]) -> str:
    """Resolve signing secret from argument, env var, or fail closed."""
    if secret:
        return secret
    env_secret = os.getenv("UNIVERSAL_KERNEL_IDENTITY_SECRET")
    if env_secret:
        return env_secret
    raise KernelConfigurationError("signing secret is required for JWT operations")


class IdentityRegistry:
    """In-memory principal registry for neutral identity operations."""

    def __init__(self) -> None:
        self._store: Dict[str, Dict[str, Any]] = {}

    def register(
        self,
        password: str,
        tenant_ids: Optional[List[str]] = None,
        project_ids: Optional[List[str]] = None,
        roles: Optional[List[str]] = None,
        email: Optional[str] = None,
        principal_id: Optional[str] = None,
    ) -> Principal:
        _validate_password(password)
        pid = principal_id or str(uuid.uuid4())
        if pid in self._store:
            raise ValueError(f"principal '{pid}' already exists")
        principal = Principal(
            id=pid,
            tenant_ids=list(tenant_ids or []),
            project_ids=list(project_ids or []),
            roles=list(roles or []),
            email=email,
        )
        self._store[pid] = {
            "principal": principal,
            "password_hash": _hash_password(password),
        }
        return principal

    def authenticate(self, principal_id: str, password: str) -> Principal:
        record = self._store.get(principal_id)
        if record is None:
            raise UnknownPrincipalError("principal not found")
        if not _verify_password(password, record["password_hash"]):
            raise UnknownPrincipalError("authentication failed")
        return record["principal"]

    def get(self, principal_id: str) -> Optional[Principal]:
        record = self._store.get(principal_id)
        return record["principal"] if record else None

    def reset(self) -> None:
        self._store.clear()


# Global registry used by module-level helpers. Tests should call reset().
_default_registry = IdentityRegistry()


def reset_identity_store() -> None:
    """Reset the global identity registry (tests only)."""
    _default_registry.reset()


def register_principal(
    password: str,
    tenant_ids: Optional[List[str]] = None,
    project_ids: Optional[List[str]] = None,
    roles: Optional[List[str]] = None,
    email: Optional[str] = None,
    principal_id: Optional[str] = None,
) -> Principal:
    """Register a principal with a bcrypt-hashed password."""
    return _default_registry.register(
        password=password,
        tenant_ids=tenant_ids,
        project_ids=project_ids,
        roles=roles,
        email=email,
        principal_id=principal_id,
    )


def authenticate_principal(principal_id: str, password: str) -> Principal:
    """Authenticate a principal; fail closed on unknown or bad credentials."""
    return _default_registry.authenticate(principal_id, password)


def issue_token(
    principal: Principal,
    expires_in: int = DEFAULT_TOKEN_TTL_SECONDS,
    secret: Optional[str] = None,
) -> str:
    """Issue a JWT for a principal."""
    signing_secret = _resolve_secret(secret)
    payload = {
        "principal_id": principal.id,
        "tenant_ids": principal.tenant_ids,
        "project_ids": principal.project_ids,
        "roles": principal.roles,
        "exp": datetime.now(timezone.utc) + timedelta(seconds=expires_in),
    }
    return jwt.encode(payload, signing_secret, algorithm=ALGORITHM)


def verify_token(token: str, secret: Optional[str] = None) -> Dict[str, Any]:
    """Verify a JWT and return its payload; fail closed on any error."""
    signing_secret = _resolve_secret(secret)
    try:
        return jwt.decode(token, signing_secret, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError("token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenExpiredError("token is invalid") from exc
