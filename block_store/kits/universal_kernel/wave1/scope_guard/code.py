"""Neutral tenant/project/resource scope isolation guard."""

from __future__ import annotations

from typing import Any, Optional


class ScopeViolation(Exception):
    """Raised when a principal attempts access outside its assigned scope."""


class ScopeGuard:
    """Enforce isolation between tenants, projects, and resources."""

    def assert_in_scope(
        self,
        principal: Dict[str, Any],
        tenant_id: Optional[str] = None,
        project_id: Optional[str] = None,
        resource_id: Optional[str] = None,
    ) -> None:
        """Raise ``ScopeViolation`` if the principal cannot access the scope."""
        principal_tenants = set(principal.get("tenant_ids") or [])
        principal_projects = set(principal.get("project_ids") or [])
        principal_resources = set(principal.get("resource_ids") or [])

        if tenant_id is not None:
            if tenant_id not in principal_tenants:
                raise ScopeViolation(
                    f"tenant '{tenant_id}' is outside principal scope"
                )

        if project_id is not None:
            if project_id not in principal_projects:
                raise ScopeViolation(
                    f"project '{project_id}' is outside principal scope"
                )

        if resource_id is not None:
            if resource_id not in principal_resources:
                raise ScopeViolation(
                    f"resource '{resource_id}' is outside principal scope"
                )


def assert_in_scope(
    principal: Dict[str, Any],
    tenant_id: Optional[str] = None,
    project_id: Optional[str] = None,
    resource_id: Optional[str] = None,
) -> None:
    """Raise ``ScopeViolation`` if the principal cannot access the scope."""
    ScopeGuard().assert_in_scope(principal, tenant_id, project_id, resource_id)
