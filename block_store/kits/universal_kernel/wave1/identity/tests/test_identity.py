"""Tests for the neutral identity sub-kit."""

import pytest

from block_store.kits.universal_kernel.wave1.identity import (
    KernelConfigurationError,
    TokenExpiredError,
    UnknownPrincipalError,
    WeakPasswordError,
    authenticate_principal,
    issue_token,
    register_principal,
    reset_identity_store,
    verify_token,
)


@pytest.fixture(autouse=True)
def _clean_identity_store():
    reset_identity_store()
    yield
    reset_identity_store()


def test_register_and_authenticate_principal():
    principal = register_principal(
        password="Secret123",
        tenant_ids=["tenant-1"],
        project_ids=["project-1"],
        roles=["admin"],
        email="principal@example.com",
        principal_id="principal-1",
    )
    assert principal.id == "principal-1"
    assert principal.tenant_ids == ["tenant-1"]
    authenticated = authenticate_principal("principal-1", "Secret123")
    assert authenticated.id == "principal-1"


def test_weak_password_is_rejected():
    with pytest.raises(WeakPasswordError):
        register_principal(password="short")
    with pytest.raises(WeakPasswordError):
        register_principal(password="nondigits")


def test_unknown_principal_is_rejected():
    with pytest.raises(UnknownPrincipalError):
        authenticate_principal("ghost", "Secret123")


def test_wrong_password_is_rejected():
    register_principal(password="Secret123", principal_id="principal-1")
    with pytest.raises(UnknownPrincipalError):
        authenticate_principal("principal-1", "Wrong1234")


def test_issue_and_verify_token():
    principal = register_principal(
        password="Secret123",
        principal_id="principal-1",
        roles=["admin"],
    )
    token = issue_token(principal, secret="test-secret")
    payload = verify_token(token, secret="test-secret")
    assert payload["principal_id"] == "principal-1"
    assert payload["roles"] == ["admin"]


def test_expired_token_is_rejected():
    principal = register_principal(password="Secret123", principal_id="principal-1")
    token = issue_token(principal, expires_in=-1, secret="test-secret")
    with pytest.raises(TokenExpiredError):
        verify_token(token, secret="test-secret")


def test_missing_secret_fails_closed():
    principal = register_principal(password="Secret123", principal_id="principal-1")
    with pytest.raises(KernelConfigurationError):
        issue_token(principal)
