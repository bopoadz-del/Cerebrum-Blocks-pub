"""Tests for the neutral scope guard sub-kit."""

import pytest

from block_store.kits.universal_kernel.wave1.scope_guard import (
    ScopeViolation,
    assert_in_scope,
)


PRINCIPAL = {
    "tenant_ids": ["tenant-1"],
    "project_ids": ["project-1", "project-2"],
    "resource_ids": ["resource-1"],
}


def test_principal_is_in_scope():
    assert_in_scope(
        PRINCIPAL,
        tenant_id="tenant-1",
        project_id="project-1",
        resource_id="resource-1",
    )


def test_cross_tenant_access_is_denied():
    with pytest.raises(ScopeViolation, match="tenant"):
        assert_in_scope(PRINCIPAL, tenant_id="tenant-2")


def test_cross_project_access_is_denied():
    with pytest.raises(ScopeViolation, match="project"):
        assert_in_scope(PRINCIPAL, tenant_id="tenant-1", project_id="project-3")


def test_resource_outside_scope_is_denied():
    with pytest.raises(ScopeViolation, match="resource"):
        assert_in_scope(PRINCIPAL, resource_id="resource-2")


def test_no_scope_arguments_passes():
    assert_in_scope(PRINCIPAL)
