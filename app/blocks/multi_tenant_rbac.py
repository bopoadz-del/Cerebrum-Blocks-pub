"""Multi-tenant RBAC, fail closed.

Donor: <private-repo> backend/app/auth/dependencies.py and
backend/tests/auth/test_rbac.py
Ported: require_permission, require_any, require_all, tenant and project
visibility that exclude non-members.
Left behind: SQLAlchemy, FastAPI, JWT decode (callers pass a principal dict).
Did not touch governance or audit.
Classification: verified_executable.
Membership is in-process only.
"""
from __future__ import annotations

from typing import Dict, Iterable

from app.core.universal_base import UniversalBlock


def has_permission(granted, permission: str) -> bool:
    return permission in (granted or [])


def has_any(granted, permissions: Iterable[str]) -> bool:
    have = set(granted or [])
    return any(item in have for item in permissions)


def has_all(granted, permissions: Iterable[str]) -> bool:
    have = set(granted or [])
    needed = list(permissions)
    return bool(needed) and all(item in have for item in needed)


class MultiTenantRbacBlock(UniversalBlock):
    """In-process tenant and project membership. Missing membership is denial."""

    name = "multi_tenant_rbac"
    version = "1.0.0"
    classification = "verified_executable"
    requires = []
    layer = 1
    tags = ["rbac", "tenant"]
    default_config = {"persistence": "in_process"}
    ui_schema = {"input": {"type": "json"}, "output": {"type": "json"}, "params": [], "quick_actions": []}

    def __init__(self, hal_block=None, config=None):
        super().__init__(hal_block, config)
        self.tenants = {}
        self.members = {}
        self.projects = {}
        self.project_members = {}

    def create_tenant(self, data: Dict) -> Dict:
        tenant_id = (data.get("tenant_id") or "").strip()
        owner = (data.get("owner_id") or "").strip()
        if not tenant_id or not owner:
            return {"status": "error", "error": "tenant_id and owner_id required"}
        if tenant_id in self.tenants:
            return {"status": "error", "error": "tenant exists"}
        self.tenants[tenant_id] = {"name": data.get("name") or tenant_id}
        self.members[(owner, tenant_id)] = "owner"
        return {"status": "ok", "tenant_id": tenant_id}

    def add_member(self, data: Dict) -> Dict:
        tenant_id = (data.get("tenant_id") or "").strip()
        user_id = (data.get("user_id") or "").strip()
        if tenant_id not in self.tenants or not user_id:
            return {"status": "error", "error": "unknown tenant or user"}
        self.members[(user_id, tenant_id)] = data.get("role") or "member"
        return {"status": "ok"}

    def create_project(self, data: Dict) -> Dict:
        tenant_id = (data.get("tenant_id") or "").strip()
        project_id = (data.get("project_id") or "").strip()
        owner = (data.get("owner_id") or "").strip()
        if (owner, tenant_id) not in self.members:
            return {"status": "error", "error": "tenant_access_denied", "code": 403}
        if not project_id:
            return {"status": "error", "error": "project_id required"}
        self.projects[project_id] = {"tenant_id": tenant_id}
        self.project_members[(owner, project_id)] = "owner"
        return {"status": "ok", "project_id": project_id}

    def visible_tenants(self, user_id: str):
        return sorted(tid for (uid, tid) in self.members if uid == user_id)

    def visible_projects(self, user_id: str, tenant_id: str):
        if (user_id, tenant_id) not in self.members:
            return []
        return sorted(
            pid for pid, row in self.projects.items()
            if row["tenant_id"] == tenant_id and (user_id, pid) in self.project_members
        )

    def check(self, data: Dict) -> Dict:
        granted = data.get("permissions") or []
        mode = data.get("mode") or "all"
        needed = data.get("needed") or []
        if mode == "any":
            ok = has_any(granted, needed)
        elif mode == "one":
            ok = len(needed) == 1 and has_permission(granted, needed[0])
        else:
            ok = has_all(granted, needed)
        if not ok:
            return {"status": "error", "error": "permission denied", "code": 403}
        return {"status": "ok"}

    async def process(self, input_data, params=None):
        data = input_data or {}
        action = (params or {}).get("action") or data.get("action")
        if action == "create_tenant":
            return self.create_tenant(data)
        if action == "add_member":
            return self.add_member(data)
        if action == "create_project":
            return self.create_project(data)
        if action == "list_tenants":
            return {"status": "ok", "tenants": self.visible_tenants(data.get("user_id") or "")}
        if action == "list_projects":
            return {"status": "ok", "projects": self.visible_projects(data.get("user_id") or "", data.get("tenant_id") or "")}
        if action == "check":
            return self.check(data)
        return {"status": "error", "error": "Unknown action: %s" % action}
