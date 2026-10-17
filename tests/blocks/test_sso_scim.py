"""SSO SAML + SCIM provisioning tests (Cerebrum ports)."""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("ENV", "test")

from app.blocks.scim_provisioning import ScimProvisioningBlock, _hash_token
from app.blocks.sso_saml import SsoSamlBlock


def _run(coro):
    return asyncio.run(coro)


GOOD_SAML = {
    "name": "okta",
    "idp_entity_id": "https://idp.example.com",
    "idp_sso_url": "https://idp.example.com/sso",
    "idp_x509_cert": "-----BEGIN CERTIFICATE-----fake-----END CERTIFICATE-----",
    "sp_entity_id": "https://sp.example.com",
    "sp_acs_url": "https://sp.example.com/acs",
}


def test_saml_insecure_url_refused():
    b = SsoSamlBlock()
    bad = dict(GOOD_SAML, idp_sso_url="http://idp.example.com/sso")
    r = _run(b.process({"action": "register", "provider": bad}))
    assert r["status"] == "refused"
    assert "HTTPS" in r["error"]


def test_saml_missing_cert_refused():
    b = SsoSamlBlock()
    bad = {k: v for k, v in GOOD_SAML.items() if k != "idp_x509_cert"}
    r = _run(b.process({"action": "register", "provider": bad}))
    assert r["status"] == "refused"


def test_saml_register_deactivate_list():
    b = SsoSamlBlock()
    r = _run(b.process({"action": "register", "provider": GOOD_SAML}))
    assert r["status"] == "ok"
    de = _run(b.process({"action": "deactivate", "name": "okta"}))
    assert de["result"]["provider"]["is_active"] is False
    lst = _run(b.process({"action": "list"}))
    assert lst["result"]["count"] == 1


def test_scim_token_hashed_never_returned():
    b = ScimProvisioningBlock()
    r = _run(b.process({"action": "register", "provider": {"name": "azure", "auth_type": "bearer_token", "bearer_token": "s3cret", "scim_base_url": "https://scim.example.com"}}))
    assert r["status"] == "ok"
    assert "token_hash" not in r["result"]["provider"]
    assert r["result"]["provider"]["name"] == "azure"
    listed = _run(b.process({"action": "list"}))
    assert "token_hash" not in listed["result"]["providers"][0]


def test_scim_requires_https_base():
    b = ScimProvisioningBlock()
    r = _run(b.process({"action": "register", "provider": {"name": "x", "auth_type": "bearer_token", "bearer_token": "t", "scim_base_url": "http://insecure"}}))
    assert r["status"] == "refused"


def test_scim_upsert_user():
    b = ScimProvisioningBlock()
    r = _run(b.process({"action": "upsert_user", "external_id": "u-1", "attributes": {"email": "a@b.c"}}))
    assert r["status"] == "ok"
    assert r["result"]["user"]["attributes"]["email"] == "a@b.c"
