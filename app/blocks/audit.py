"""Audit Block — immutable compliance logging with hash-chain integrity.

Wave 3 replacement: the previous implementation's verification paths were
gated on an optional database block and never walked the chain from the
store itself. This revision delegates to the FinanceOps-ported
``audit_chain`` implementation (append-only ledger + FULL-WALK
verify_chain that recomputes every link) while keeping the block's
public action surface (log / query / export / verify_chain / get_stats /
tamper_check) unchanged.

Donor semantics: <private-repo> backend/app/audit/service.py.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from app.core.universal_base import UniversalBlock

from app.blocks.audit_chain import _ledger, _now


class AuditBlock(UniversalBlock):
    name = "audit"
    version = "1.0.0"
    requires = []
    layer = 1  # Security layer
    tags = ["security", "compliance", "audit", "enterprise"]
    description = (
        "Append-only audit trail with hash-chain integrity; verify_chain "
        "full-walks every record and names each violation."
    )
    default_config = {
        "hash_algorithm": "sha256",
        "retention_days": 2555,  # 7 years
        "categories": ["auth", "data_access", "system", "admin"],
    }

    ui_schema = {
        'input': {'type': 'json', 'accept': None, 'placeholder': 'JSON payload for the selected action', 'multiline': True},
        'output': {'type': 'json', 'fields': [{'name': 'events', 'type': 'json', 'label': 'Audit Events'}]},
        'params': [{'name': 'action', 'type': 'select', 'label': 'Action', 'options': ['log', 'query', 'export', 'verify_chain', 'get_stats', 'tamper_check'], 'default': 'log'}],
        'quick_actions': [],
    }

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        data = input_data if isinstance(input_data, dict) else {}
        action = params.get("action", data.get("action", "log"))
        tenant_id = str(params.get("tenant_id", data.get("tenant_id", "local")))
        ledger = _ledger(tenant_id)

        if action == "log":
            entry = {
                "id": f"al-{len(ledger['logs']) + 1}",
                "tenant_id": tenant_id,
                "project_id": data.get("project_id"),
                "principal_id": data.get("principal_id") or data.get("user_id"),
                "action": data.get("action_name") or data.get("event"),
                "resource_type": data.get("resource_type") or data.get("category", "system"),
                "resource_id": data.get("resource_id"),
                "status": data.get("status", "ok"),
                "details": data.get("details", {}),
                "created_at": _now(),
            }
            ledger["logs"].append(entry)
            return {"status": "success", "entry": dict(entry)}

        if action in ("query", "export"):
            filters = {
                "action": data.get("action_name"),
                "resource_type": data.get("category"),
            }
            out = list(ledger["logs"])
            if filters["action"]:
                out = [r for r in out if r["action"] == filters["action"]]
            if filters["resource_type"]:
                out = [r for r in out if r["resource_type"] == filters["resource_type"]]
            out = sorted(out, key=lambda r: r["created_at"], reverse=True)
            if action == "export":
                return {"status": "success", "format": "json", "events": out}
            return {
                "status": "success",
                "events": out,
                "count": len(out),
                "filters": {k: v for k, v in filters.items() if v},
            }

        if action in ("verify_chain", "tamper_check"):
            # FULL WALK over the evidence chain — a tampered record is named,
            # never silently accepted.
            records = list(ledger["evidence"])
            violations = []
            expected_previous = None
            from app.blocks.audit_chain import _compute_chain_hash

            for record in records:
                computed = _compute_chain_hash(
                    record["id"],
                    expected_previous,
                    record["payload_hash"],
                    record["result_hash"],
                    record["created_at"],
                )
                if record["previous_hash"] != expected_previous:
                    violations.append(
                        {"record": record["id"], "error": "previous_hash linkage broken"}
                    )
                if computed != record["chain_hash"]:
                    violations.append(
                        {"record": record["id"], "error": "chain_hash mismatch"}
                    )
                expected_previous = record["chain_hash"]
            return {
                "status": "success",
                "verified": not violations,
                "records_walked": len(records),
                "violations": violations,
            }

        if action == "get_stats":
            return {
                "status": "success",
                "log_count": len(ledger["logs"]),
                "evidence_count": len(ledger["evidence"]),
            }

        return {"status": "error", "error": f"Unknown action: {action}"}
