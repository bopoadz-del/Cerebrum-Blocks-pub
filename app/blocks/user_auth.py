"""User auth: bcrypt passwords, HS256 access tokens, refresh rotation, TOTP.

Donor: <private-repo> app/server/src/routes/auth.ts
Ported: bcrypt hash, access+refresh pair, refresh rotation (old token dies),
TOTP setup/verify (RFC 6238, SHA1, 30s, 6 digits).
Left behind: Prisma, email, organization billing, the Math.random backtest.
Classification: verified_executable.
Store is in-process only. JWT secret must be supplied. There is no default secret.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import struct
import time
from typing import Dict, Optional

import bcrypt

from app.core.universal_base import UniversalBlock


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def sign_access(payload: Dict, secret: str, ttl_s: int) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    body = dict(payload)
    now = int(time.time())
    body["iat"] = now
    body["exp"] = now + int(ttl_s)
    signing = _b64(json.dumps(header, separators=(",", ":"), sort_keys=True).encode()) + "." + _b64(
        json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
    )
    sig = hmac.new(secret.encode("utf-8"), signing.encode("ascii"), hashlib.sha256).digest()
    return signing + "." + _b64(sig)


def decode_access(token: str, secret: str) -> Optional[Dict]:
    parts = token.split(".")
    if len(parts) != 3:
        return None
    signing = parts[0] + "." + parts[1]
    expected = hmac.new(secret.encode("utf-8"), signing.encode("ascii"), hashlib.sha256).digest()
    try:
        got = _b64d(parts[2])
    except Exception as exc:
        raise ValueError("bad signature encoding") from exc
    if not hmac.compare_digest(expected, got):
        return None
    body = json.loads(_b64d(parts[1]))
    if int(body.get("exp", 0)) <= int(time.time()):
        return None
    return body


def totp_at(secret_b32: str, when: int, step: int = 30) -> str:
    key = base64.b32decode(secret_b32, casefold=True)
    counter = int(when // step)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code % 1_000_000).zfill(6)


class UserAuthBlock(UniversalBlock):
    """In-process user auth. Refresh tokens rotate. No default JWT secret."""

    name = "user_auth"
    version = "1.0.0"
    classification = "verified_executable"
    requires = []
    layer = 1
    tags = ["auth", "jwt", "totp"]
    default_config = {"persistence": "in_process", "access_ttl_s": 900, "refresh_ttl_s": 604800}
    ui_schema = {"input": {"type": "json"}, "output": {"type": "json"}, "params": [], "quick_actions": []}

    def __init__(self, hal_block=None, config=None):
        super().__init__(hal_block, config)
        self.users = {}
        self.refresh = {}

    def _secret(self) -> Optional[str]:
        secret = (self.config or {}).get("jwt_secret")
        if not isinstance(secret, str) or not secret:
            return None
        return secret

    def register(self, data: Dict) -> Dict:
        email = (data.get("email") or "").strip().lower()
        password = data.get("password") or ""
        if "@" not in email or len(password) < 8:
            return {"status": "error", "error": "email and password of 8+ chars required"}
        if email in self.users:
            return {"status": "error", "error": "email already registered"}
        self.users[email] = {
            "password_hash": bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)),
            "totp_secret": None,
            "totp_enabled": False,
        }
        return {"status": "ok", "email": email}

    def _issue_pair(self, email: str) -> Dict:
        secret = self._secret()
        if secret is None:
            return {"status": "error", "error": "jwt_secret required"}
        access = sign_access({"sub": email, "type": "access"}, secret, int(self.config.get("access_ttl_s") or 900))
        raw_refresh = secrets.token_urlsafe(32)
        digest = hashlib.sha256(raw_refresh.encode("utf-8")).hexdigest()
        self.refresh[digest] = {
            "email": email,
            "expires": time.time() + int(self.config.get("refresh_ttl_s") or 604800),
            "used": False,
        }
        return {"status": "ok", "access_token": access, "refresh_token": raw_refresh}

    def login(self, data: Dict) -> Dict:
        email = (data.get("email") or "").strip().lower()
        user = self.users.get(email)
        password = data.get("password") or ""
        if user is None or not bcrypt.checkpw(password.encode("utf-8"), user["password_hash"]):
            return {"status": "error", "error": "invalid credentials"}
        if user["totp_enabled"]:
            code = data.get("mfa_code") or ""
            if not self._totp_ok(user["totp_secret"], code):
                return {"status": "error", "error": "mfa required"}
        return self._issue_pair(email)

    def rotate(self, data: Dict) -> Dict:
        raw = data.get("refresh_token") or ""
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        row = self.refresh.get(digest)
        now = time.time()
        if row is None or row["used"] or row["expires"] <= now:
            return {"status": "error", "error": "invalid refresh token"}
        row["used"] = True
        return self._issue_pair(row["email"])

    def setup_totp(self, data: Dict) -> Dict:
        email = (data.get("email") or "").strip().lower()
        user = self.users.get(email)
        if user is None:
            return {"status": "error", "error": "unknown user"}
        secret = base64.b32encode(secrets.token_bytes(20)).decode("ascii")
        user["totp_secret"] = secret
        user["totp_enabled"] = False
        return {"status": "ok", "secret": secret}

    def confirm_totp(self, data: Dict) -> Dict:
        email = (data.get("email") or "").strip().lower()
        user = self.users.get(email)
        if user is None or not user.get("totp_secret"):
            return {"status": "error", "error": "totp not started"}
        if not self._totp_ok(user["totp_secret"], data.get("code") or ""):
            return {"status": "error", "error": "bad totp code"}
        user["totp_enabled"] = True
        return {"status": "ok", "totp_enabled": True}

    def _totp_ok(self, secret: str, code: str) -> bool:
        if not isinstance(code, str) or len(code) != 6 or not code.isdigit():
            return False
        now = int(time.time())
        for skew in (-30, 0, 30):
            if hmac.compare_digest(totp_at(secret, now + skew), code):
                return True
        return False

    async def process(self, input_data, params=None):
        data = input_data or {}
        action = (params or {}).get("action") or data.get("action")
        if action == "register":
            return self.register(data)
        if action == "login":
            return self.login(data)
        if action == "refresh":
            return self.rotate(data)
        if action == "setup_totp":
            return self.setup_totp(data)
        if action == "confirm_totp":
            return self.confirm_totp(data)
        return {"status": "error", "error": "Unknown action: %s" % action}
