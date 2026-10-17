"""Neutral role-permission authorization policy engine."""

from __future__ import annotations

import fnmatch
from copy import deepcopy
from typing import Any, Dict, List, Optional


class AuthorizationPolicyError(Exception):
    """Raised when the authorization policy is misconfigured or missing."""


class PolicyNotLoadedError(AuthorizationPolicyError):
    """Raised when a default policy has not been configured."""


class Permission:
    """A single permission statement within a role."""

    def __init__(self, action: str, resource: str, effect: str = "allow") -> None:
        self.action = action
        self.resource = resource
        self.effect = effect.lower()
        if self.effect not in {"allow", "deny"}:
            raise ValueError(f"invalid effect '{effect}'; use allow or deny")

    def matches(self, action: str, resource: str) -> bool:
        return fnmatch.fnmatchcase(action, self.action) and fnmatch.fnmatchcase(
            resource, self.resource
        )


class Role:
    """A named role holding permission statements."""

    def __init__(self, name: str, permissions: Optional[List[Dict[str, Any]]] = None) -> None:
        self.name = name
        self.permissions = [Permission(**p) for p in (permissions or [])]


class AuthorizationPolicy:
    """Role-permission graph with explicit deny precedence."""

    def __init__(self, policy: Optional[Dict[str, Any]] = None) -> None:
        self._roles: Dict[str, Role] = {}
        if policy is not None:
            self.load(policy)

    def load(self, policy: Dict[str, Any]) -> "AuthorizationPolicy":
        self._roles.clear()
        for name, definition in (policy.get("roles") or {}).items():
            perms = definition.get("permissions") if isinstance(definition, dict) else definition
            self._roles[name] = Role(name, perms)
        return self

    def permitted(
        self,
        principal: Dict[str, Any],
        action: str,
        resource: str,
    ) -> Dict[str, Any]:
        """Evaluate whether ``action`` on ``resource`` is permitted.

        Returns ``{allowed: bool, reason: str, matched_roles: list}``.
        """
        roles = list(principal.get("roles") or [])
        if not roles:
            return {
                "allowed": False,
                "reason": "principal has no roles",
                "matched_roles": [],
            }

        allowed = False
        matched_roles: List[str] = []
        for role_name in roles:
            role = self._roles.get(role_name)
            if role is None:
                continue
            for permission in role.permissions:
                if permission.matches(action, resource):
                    if permission.effect == "deny":
                        return {
                            "allowed": False,
                            "reason": f"explicit deny matched in role '{role_name}'",
                            "matched_roles": [role_name],
                        }
                    allowed = True
                    if role_name not in matched_roles:
                        matched_roles.append(role_name)

        if allowed:
            return {
                "allowed": True,
                "reason": "permission granted by role policy",
                "matched_roles": matched_roles,
            }
        return {
            "allowed": False,
            "reason": "no matching permission",
            "matched_roles": [],
        }


# Module-level default policy instance.
_default_policy: Optional[AuthorizationPolicy] = None


def load_policy(policy: Dict[str, Any]) -> AuthorizationPolicy:
    """Load the module-level default policy."""
    global _default_policy
    _default_policy = AuthorizationPolicy(policy)
    return _default_policy


def reset_policy() -> None:
    """Clear the module-level default policy (tests only)."""
    global _default_policy
    _default_policy = None


def _get_policy(policy: Optional[AuthorizationPolicy] = None) -> AuthorizationPolicy:
    if policy is not None:
        return policy
    if _default_policy is None:
        raise PolicyNotLoadedError("no authorization policy configured")
    return _default_policy


def permitted(
    principal: Dict[str, Any],
    action: str,
    resource: str,
    policy: Optional[AuthorizationPolicy] = None,
) -> Dict[str, Any]:
    """Evaluate whether ``action`` on ``resource`` is permitted."""
    try:
        active_policy = _get_policy(policy)
    except PolicyNotLoadedError:
        return {
            "allowed": False,
            "reason": "no authorization policy configured",
            "matched_roles": [],
        }
    return active_policy.permitted(principal, action, resource)
