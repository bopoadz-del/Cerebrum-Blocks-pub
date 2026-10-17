"""Offline tests for the google_drive service-account path: JWT assertion
minting (RS256 with a locally generated key — no network), mode
disclosure, and honest unconfigured refusal.
"""

from __future__ import annotations

import json
import os

import pytest

from app.blocks.google_drive import (
    GoogleDriveBlock,
    _auth_mode,
    _load_service_account,
    _service_account_jwt,
)


@pytest.fixture()
def service_account_env(tmp_path, monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    blob = json.dumps(
        {
            "client_email": "sa@example.iam.gserviceaccount.com",
            "private_key": pem,
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", blob)
    return blob


def _decode_segment(segment: str) -> dict:
    import base64

    padded = segment + "=" * (-len(segment) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


def test_service_account_jwt_structure(service_account_env):
    sa = _load_service_account()
    assert sa is not None
    assert sa["client_email"] == "sa@example.iam.gserviceaccount.com"

    jwt = _service_account_jwt(sa)
    header_b64, claims_b64, signature = jwt.split(".")
    header = _decode_segment(header_b64)
    claims = _decode_segment(claims_b64)
    assert header == {"alg": "RS256", "typ": "JWT"}
    assert claims["iss"] == "sa@example.iam.gserviceaccount.com"
    assert claims["aud"] == "https://oauth2.googleapis.com/token"
    assert "https://www.googleapis.com/auth/drive.readonly" in claims["scope"]
    assert claims["exp"] - claims["iat"] == 3600
    assert signature  # signed, not empty


def test_auth_mode_disclosure(service_account_env, monkeypatch):
    assert _auth_mode() == "service_account"
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "user-token")
    assert _auth_mode() == "user_token"
    monkeypatch.delenv("GOOGLE_ACCESS_TOKEN")
    assert _auth_mode() == "unconfigured"


def test_sa_file_path_support(service_account_env, tmp_path, monkeypatch):
    blob = service_account_env
    path = tmp_path / "sa.json"
    path.write_text(blob, encoding="utf-8")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", str(path))
    assert _load_service_account()["client_email"] == "sa@example.iam.gserviceaccount.com"


@pytest.mark.asyncio
async def test_list_refuses_honestly_when_unconfigured(monkeypatch):
    for var in (
        "GOOGLE_SERVICE_ACCOUNT_JSON",
        "GOOGLE_ACCESS_TOKEN",
        "GOOGLE_REFRESH_TOKEN",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
    ):
        monkeypatch.delenv(var, raising=False)
    block = GoogleDriveBlock()
    envelope = await block.execute(None, {"operation": "list"})
    result = envelope["result"]
    assert result["status"] == "error"
    assert "Not authenticated" in result["error"]
