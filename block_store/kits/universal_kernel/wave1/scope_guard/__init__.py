"""Scope guard sub-kit: tenant/project/resource isolation enforcement."""

from .code import ScopeGuard, ScopeViolation, assert_in_scope

__all__ = ["ScopeGuard", "ScopeViolation", "assert_in_scope"]
