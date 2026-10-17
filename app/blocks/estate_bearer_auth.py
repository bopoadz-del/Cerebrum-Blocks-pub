"""Estate-scoped bearer auth.

Donor: <private-repo> app/steward/auth.py
Ported: hash_token (HMAC-SHA256 + pepper), bearer parse, estate scope check,
curator role gate.
Left behind: SQLAlchemy, FastAPI, demo-bypass admin (that path is refused).
Classification: verified_executable.
Token store is in-process only and is lost on restart.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

from app.core.universal_base import UniversalBlock


def hash_token(raw_token: str, pepper: str) -> str:
    return hmac.new(pepper.encode("utf-8"), raw_token.encode("utf-8"), hashlib.sha256).hexdigest()


def parse_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


class EstateBearerAuthBlock(UniversalBlock):
    """In-process estate bearer tokens. No demo bypass. No database."""

    name = "estate_bearer_auth"
    version = "1.0.0"
    classification = "verified_executable"
    requires = []
    layer = 1
    tags = ["auth", "estate", "rbac"]
    default_config = {"persistence": "in_process"}
    ui_schema = {"input": {"type": "json"}, "output": {"type": "json"}, "params": [], "quick_actions": []}

    def __init__(self, hal_block=None, config=None):
        super().__init__(hal_block, config)
        self.principals = {}
        self.tokens = {}
        self.access = {}

    def _pepper(self) -> Optional[str]:
        pepper = (self.config or {}).get("pepper")
        if not isinstance(pepper, str) or not pepper:
            return None
        return pepper

    def issue(self, data: Dict) -> Dict:
        pepper = self._pepper()
        if pepper is None:
            return {"status": "error", "error": "pepper required"}
        principal_id = (data.get("principal_id") or "").strip()
        tenant_id = (data.get("tenant_id") or "").strip()
        estate_id = (data.get("estate_id") or "").strip()
        if not principal_id or not tenant_id or not estate_id:
            return {"status": "error", "error": "principal_id, tenant_id, estate_id required"}
        role = data.get("role") or "viewer"
        estate_role = data.get("estate_role") or "viewer"
        self.principals[principal_id] = {
            "display_name": data.get("display_name") or principal_id,
            "role": role,
            "enabled": True,
        }
        self.access[(principal_id, tenant_id, estate_id)] = estate_role
        raw = secrets.token_urlsafe(32)
        expires = datetime.now(timezone.utc) + timedelta(hours=1)
        self.tokens[hash_token(raw, pepper)] = {
            "principal_id": principal_id,
            "expires_at": expires,
            "revoked": False,
        }
        return {"status": "ok", "token": raw, "expires_at": expires.isoformat()}

    def resolve(self, data: Dict) -> Dict:
        pepper = self._pepper()
        if pepper is None:
            return {"status": "error", "error": "pepper required"}
        raw = parse_bearer(data.get("authorization"))
        if not raw:
            return {"status": "error", "error": "invalid_token", "code": 401}
        row = self.tokens.get(hash_token(raw, pepper))
        now = datetime.now(timezone.utc)
        if row is None or row["revoked"] or row["expires_at"] <= now:
            return {"status": "error", "error": "invalid_token", "code": 401}
        principal = self.principals.get(row["principal_id"])
        if principal is None or not principal["enabled"]:
            return {"status": "error", "error": "principal_disabled", "code": 403}
        tenant = (data.get("tenant_id") or "").strip()
        estate = (data.get("estate_id") or "").strip()
        if not tenant or not estate:
            return {"status": "error", "error": "estate_scope_required", "code": 400}
        estate_role = self.access.get((row["principal_id"], tenant, estate))
        if estate_role is None:
            return {"status": "error", "error": "estate_access_denied", "code": 403}
        return {
            "status": "ok",
            "principal_id": row["principal_id"],
            "display_name": principal["display_name"],
            "role": principal["role"],
            "tenant_id": tenant,
            "estate_id": estate,
            "estate_role": estate_role,
            "auth_mode": "bearer",
        }

    def authorize(self, principal: Dict, tenant_id: str, estate_id: str, require_curator: bool = False) -> Dict:
        tenant = (tenant_id or "").strip()
        estate = (estate_id or "").strip()
        if not tenant or not estate:
            return {"status": "error", "error": "estate_scope_required", "code": 400}
        if principal.get("tenant_id") != tenant or principal.get("estate_id") != estate:
            return {"status": "error", "error": "estate_access_denied", "code": 403}
        if require_curator and principal.get("estate_role") not in {"curator", "admin"}:
            if principal.get("role") != "admin":
                return {"status": "error", "error": "curator_required", "code": 403}
        return {"status": "ok", "principal": principal}

    async def process(self, input_data, params=None):
        data = input_data or {}
        action = (params or {}).get("action") or data.get("action")
        if action == "issue":
            return self.issue(data)
        if action == "resolve":
            return self.resolve(data)
        if action == "authorize":
            resolved = data.get("principal")
            if not isinstance(resolved, dict):
                return {"status": "error", "error": "principal required"}
            return self.authorize(resolved, data.get("tenant_id") or "", data.get("estate_id") or "", bool(data.get("require_curator")))
        return {"status": "error", "error": "Unknown action: %s" % action}
