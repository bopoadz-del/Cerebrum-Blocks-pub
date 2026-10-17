"""Agency hierarchy Store block for insurance distribution channels."""

from datetime import date
from typing import Any, Dict, List, Optional, Set, TypedDict

from app.core.universal_base import UniversalBlock


class AgencyHierarchyNode(TypedDict):
    """Distribution hierarchy node."""

    id: str
    role: str
    parent_id: Optional[str]
    name: str
    effective_from: Optional[str]
    effective_to: Optional[str]
    metadata: Dict[str, Any]


class AgencyHierarchyResult(TypedDict, total=False):
    """Typed result envelope returned by process operations."""

    status: str
    operation: str
    node: AgencyHierarchyNode
    root: AgencyHierarchyNode
    nodes: List[AgencyHierarchyNode]
    path: List[AgencyHierarchyNode]
    edges: List[Dict[str, str]]
    valid: bool
    errors: List[str]
    warnings: List[str]
    count: int
    node_count: int
    root_ids: List[str]
    message: str
    error: str


class AgencyHierarchyBlock(UniversalBlock):
    """In-memory hierarchy store for F1 agency and producer distribution."""

    name = "agency_hierarchy"
    version = "1.0.0"
    description = "Insurance agency hierarchy Store block for agent, agency, MGA/FMO, and carrier distribution trees"
    layer = 3
    tags = ["domain", "insurance", "agency", "producer", "store"]
    requires: List[str] = []

    default_config = {
        "allowed_roles": ["agent", "agency", "mga_fmo", "carrier"],
    }

    ui_schema = {
        "input": {
            "type": "json",
            "placeholder": '{"operation": "upsert_node", "node": {"id": "agent-1", "role": "agent", "parent_id": "agency-1", "name": "Jane Producer"}}',
            "multiline": True,
        },
        "output": {
            "type": "json",
            "fields": [
                {"name": "node", "type": "json", "label": "Node"},
                {"name": "nodes", "type": "json", "label": "Hierarchy Nodes"},
                {"name": "valid", "type": "boolean", "label": "Valid"},
            ],
        },
        "quick_actions": [
            {"icon": "S", "label": "Subtree", "prompt": "Get the subtree for a hierarchy node"},
            {"icon": "V", "label": "Validate", "prompt": "Validate the agency hierarchy"},
        ],
    }

    _ROLE_RANK = {
        "agent": 0,
        "agency": 1,
        "mga_fmo": 2,
        "carrier": 3,
    }

    def __init__(self, hal_block=None, config: Dict = None):
        super().__init__(hal_block, config)
        self._nodes: Dict[str, AgencyHierarchyNode] = {}

    async def process(self, input_data: Any, params: Dict = None) -> AgencyHierarchyResult:
        """Route hierarchy Store operations."""

        params = params or {}
        data = input_data if isinstance(input_data, dict) else {}
        operation = (
            params.get("operation")
            or params.get("action")
            or data.get("operation")
            or data.get("action")
            or "validate_hierarchy"
        )

        if operation == "upsert_node":
            return self._upsert_node(data)
        if operation == "get_subtree":
            return self._get_subtree(data, params)
        if operation == "path_to_root":
            return self._path_to_root(data)
        if operation == "validate_hierarchy":
            return self._validate_hierarchy()

        return {
            "status": "error",
            "operation": str(operation),
            "error": f"Unknown operation: {operation}",
        }

    def _upsert_node(self, data: Dict[str, Any]) -> AgencyHierarchyResult:
        raw_node = data.get("node") if isinstance(data.get("node"), dict) else data
        node = self._normalize_node(raw_node)
        errors = self._validate_node_shape(node)

        parent_id = node.get("parent_id")
        if parent_id:
            parent = self._nodes.get(parent_id)
            if not parent:
                errors.append(f"parent_id '{parent_id}' does not exist")
            elif not self._is_allowed_parent(child_role=node["role"], parent_role=parent["role"]):
                errors.append(
                    f"parent role '{parent['role']}' cannot contain child role '{node['role']}'"
                )

        if parent_id == node.get("id"):
            errors.append("node cannot be its own parent")

        if errors:
            return {
                "status": "error",
                "operation": "upsert_node",
                "valid": False,
                "errors": errors,
                "node": node,
            }

        prior = self._copy_node(self._nodes[node["id"]]) if node["id"] in self._nodes else None
        self._nodes[node["id"]] = node
        validation = self._validate_hierarchy()
        if not validation.get("valid", False):
            if prior is None:
                self._nodes.pop(node["id"], None)
            else:
                self._nodes[node["id"]] = prior
            return {
                "status": "error",
                "operation": "upsert_node",
                "valid": False,
                "errors": validation.get("errors", []),
                "node": node,
            }

        return {
            "status": "success",
            "operation": "upsert_node",
            "node": self._copy_node(node),
            "message": f"Node '{node['id']}' upserted",
        }

    def _get_subtree(self, data: Dict[str, Any], params: Dict[str, Any]) -> AgencyHierarchyResult:
        node_id = data.get("node_id") or data.get("id") or params.get("node_id") or params.get("id")
        if not node_id:
            return self._error("get_subtree", "node_id is required")
        if node_id not in self._nodes:
            return self._error("get_subtree", f"node_id '{node_id}' not found")

        as_of_value = data.get("as_of") or params.get("as_of")
        include_inactive = bool(data.get("include_inactive", params.get("include_inactive", True)))
        as_of = self._parse_date(as_of_value) if as_of_value else None
        if as_of_value and as_of is None:
            return self._error("get_subtree", f"as_of '{as_of_value}' is not a valid ISO date")

        nodes: List[AgencyHierarchyNode] = []
        edges: List[Dict[str, str]] = []
        visited: Set[str] = set()

        def visit(current_id: str) -> None:
            if current_id in visited:
                return
            visited.add(current_id)
            current = self._nodes[current_id]
            if include_inactive or self._is_active(current, as_of):
                nodes.append(self._copy_node(current))

            child_ids = sorted(
                child["id"]
                for child in self._nodes.values()
                if child.get("parent_id") == current_id
            )
            for child_id in child_ids:
                child = self._nodes[child_id]
                if include_inactive or self._is_active(child, as_of):
                    edges.append({"parent_id": current_id, "child_id": child_id})
                visit(child_id)

        visit(str(node_id))
        return {
            "status": "success",
            "operation": "get_subtree",
            "root": self._copy_node(self._nodes[str(node_id)]),
            "nodes": nodes,
            "edges": edges,
            "count": len(nodes),
        }

    def _path_to_root(self, data: Dict[str, Any]) -> AgencyHierarchyResult:
        node_id = data.get("node_id") or data.get("id")
        if not node_id:
            return self._error("path_to_root", "node_id is required")
        if node_id not in self._nodes:
            return self._error("path_to_root", f"node_id '{node_id}' not found")

        path: List[AgencyHierarchyNode] = []
        visited: Set[str] = set()
        current_id: Optional[str] = str(node_id)

        while current_id:
            if current_id in visited:
                return self._error("path_to_root", f"cycle detected at node_id '{current_id}'")
            visited.add(current_id)

            current = self._nodes.get(current_id)
            if not current:
                return self._error("path_to_root", f"missing parent node_id '{current_id}'")

            path.append(self._copy_node(current))
            current_id = current.get("parent_id")

        return {
            "status": "success",
            "operation": "path_to_root",
            "path": path,
            "count": len(path),
        }

    def _validate_hierarchy(self) -> AgencyHierarchyResult:
        errors: List[str] = []
        warnings: List[str] = []

        for node in self._nodes.values():
            errors.extend(self._validate_node_shape(node, prefix=f"node '{node['id']}': "))
            parent_id = node.get("parent_id")
            if not parent_id:
                continue

            parent = self._nodes.get(parent_id)
            if not parent:
                errors.append(f"node '{node['id']}': parent_id '{parent_id}' does not exist")
                continue

            if not self._is_allowed_parent(child_role=node["role"], parent_role=parent["role"]):
                errors.append(
                    f"node '{node['id']}': parent role '{parent['role']}' cannot contain child role '{node['role']}'"
                )

            if parent.get("effective_from") and node.get("effective_from"):
                parent_start = self._parse_date(parent["effective_from"])
                child_start = self._parse_date(node["effective_from"])
                if parent_start and child_start and child_start < parent_start:
                    warnings.append(
                        f"node '{node['id']}': effective_from precedes parent '{parent_id}'"
                    )

            if parent.get("effective_to") and node.get("effective_to"):
                parent_end = self._parse_date(parent["effective_to"])
                child_end = self._parse_date(node["effective_to"])
                if parent_end and child_end and child_end > parent_end:
                    warnings.append(
                        f"node '{node['id']}': effective_to exceeds parent '{parent_id}'"
                    )

        errors.extend(self._cycle_errors())
        root_ids = sorted(node["id"] for node in self._nodes.values() if not node.get("parent_id"))

        return {
            "status": "success" if not errors else "error",
            "operation": "validate_hierarchy",
            "valid": not errors,
            "errors": errors,
            "warnings": warnings,
            "node_count": len(self._nodes),
            "root_ids": root_ids,
        }

    def _normalize_node(self, raw_node: Dict[str, Any]) -> AgencyHierarchyNode:
        metadata = raw_node.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {"value": metadata}

        parent_id = raw_node.get("parent_id")
        if parent_id in ("", None):
            parent_id = None
        else:
            parent_id = str(parent_id)

        return {
            "id": str(raw_node.get("id", "")).strip(),
            "role": str(raw_node.get("role", "")).strip().lower(),
            "parent_id": parent_id,
            "name": str(raw_node.get("name", "")).strip(),
            "effective_from": self._normalize_date_value(raw_node.get("effective_from")),
            "effective_to": self._normalize_date_value(raw_node.get("effective_to")),
            "metadata": metadata,
        }

    def _validate_node_shape(self, node: AgencyHierarchyNode, prefix: str = "") -> List[str]:
        errors: List[str] = []
        if not node.get("id"):
            errors.append(f"{prefix}id is required")
        if node.get("role") not in self._ROLE_RANK:
            errors.append(f"{prefix}role must be one of {sorted(self._ROLE_RANK)}")
        if not node.get("name"):
            errors.append(f"{prefix}name is required")

        effective_from = node.get("effective_from")
        effective_to = node.get("effective_to")
        from_date = self._parse_date(effective_from) if effective_from else None
        to_date = self._parse_date(effective_to) if effective_to else None

        if effective_from and from_date is None:
            errors.append(f"{prefix}effective_from must be an ISO date")
        if effective_to and to_date is None:
            errors.append(f"{prefix}effective_to must be an ISO date")
        if from_date and to_date and to_date < from_date:
            errors.append(f"{prefix}effective_to cannot be before effective_from")

        return errors

    def _cycle_errors(self) -> List[str]:
        errors: List[str] = []
        checked: Set[str] = set()

        for node_id in self._nodes:
            if node_id in checked:
                continue
            path: Set[str] = set()
            current_id: Optional[str] = node_id
            while current_id:
                if current_id in path:
                    errors.append(f"cycle detected at node_id '{current_id}'")
                    break
                if current_id in checked:
                    break
                path.add(current_id)
                parent_id = self._nodes.get(current_id, {}).get("parent_id")
                current_id = parent_id if parent_id in self._nodes else None
            checked.update(path)

        return errors

    def _is_allowed_parent(self, child_role: str, parent_role: str) -> bool:
        child_rank = self._ROLE_RANK.get(child_role)
        parent_rank = self._ROLE_RANK.get(parent_role)
        if child_rank is None or parent_rank is None:
            return False
        return parent_rank >= child_rank

    def _is_active(self, node: AgencyHierarchyNode, as_of: Optional[date]) -> bool:
        check_date = as_of or date.today()
        effective_from = self._parse_date(node.get("effective_from"))
        effective_to = self._parse_date(node.get("effective_to"))
        if effective_from and check_date < effective_from:
            return False
        if effective_to and check_date > effective_to:
            return False
        return True

    def _normalize_date_value(self, value: Any) -> Optional[str]:
        if value in ("", None):
            return None
        return str(value)

    def _parse_date(self, value: Any) -> Optional[date]:
        if value in ("", None):
            return None
        try:
            return date.fromisoformat(str(value))
        except ValueError:
            return None

    def _copy_node(self, node: AgencyHierarchyNode) -> AgencyHierarchyNode:
        return {
            "id": node["id"],
            "role": node["role"],
            "parent_id": node.get("parent_id"),
            "name": node["name"],
            "effective_from": node.get("effective_from"),
            "effective_to": node.get("effective_to"),
            "metadata": dict(node.get("metadata", {})),
        }

    def _error(self, operation: str, message: str) -> AgencyHierarchyResult:
        return {
            "status": "error",
            "operation": operation,
            "error": message,
            "errors": [message],
        }
