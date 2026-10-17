"""Tests for the neutral authorization policy sub-kit."""

import pytest

from block_store.kits.universal_kernel.wave1.authorization_policy import (
    load_policy,
    permitted,
    reset_policy,
)


@pytest.fixture(autouse=True)
def _clean_policy():
    reset_policy()
    yield
    reset_policy()


SAMPLE_POLICY = {
    "roles": {
        "admin": {
            "permissions": [
                {"action": "*", "resource": "*", "effect": "allow"},
            ]
        },
        "editor": {
            "permissions": [
                {"action": "read", "resource": "*", "effect": "allow"},
                {"action": "write", "resource": "doc/*", "effect": "allow"},
            ]
        },
        "viewer": {
            "permissions": [
                {"action": "read", "resource": "report/*", "effect": "allow"},
            ]
        },
        "denier": {
            "permissions": [
                {"action": "read", "resource": "secret/*", "effect": "deny"},
            ]
        },
    }
}


def test_admin_may_act_on_any_resource():
    load_policy(SAMPLE_POLICY)
    result = permitted(
        {"roles": ["admin"]},
        action="delete",
        resource="tenant/1/project/2",
    )
    assert result["allowed"] is True
    assert "admin" in result["matched_roles"]


def test_editor_write_allowed_within_pattern():
    load_policy(SAMPLE_POLICY)
    result = permitted({"roles": ["editor"]}, action="write", resource="doc/budget")
    assert result["allowed"] is True


def test_viewer_cannot_write():
    load_policy(SAMPLE_POLICY)
    result = permitted({"roles": ["viewer"]}, action="write", resource="report/summary")
    assert result["allowed"] is False
    assert result["reason"] == "no matching permission"


def test_explicit_deny_overrides_allow():
    load_policy(SAMPLE_POLICY)
    result = permitted({"roles": ["admin", "denier"]}, action="read", resource="secret/file")
    assert result["allowed"] is False
    assert "deny" in result["reason"]


def test_missing_policy_fails_closed():
    result = permitted({"roles": ["admin"]}, action="read", resource="any")
    assert result["allowed"] is False
    assert "no authorization policy configured" in result["reason"]


def test_principal_without_roles_is_denied():
    load_policy(SAMPLE_POLICY)
    result = permitted({"roles": []}, action="read", resource="report/summary")
    assert result["allowed"] is False
    assert "no roles" in result["reason"]
