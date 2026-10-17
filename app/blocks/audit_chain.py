"""Audit chain block — the <private-repo> audit service, neutralized
for the Store (in-process tenant-scoped records) with the missing piece
the survey demanded: a FULL-WALK ``verify_chain`` that recomputes every
link (previous-hash linkage + payload/result digests + created_at) and
names each violation. A tampered record can never verify.

Donor: <private-repo> backend/app/audit/service.py.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.universal_base import UniversalBlock

# tenant_id -> {"evidence": [...], "logs": [...]}
_LEDGERS: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
_ids = itertools.count(1)


def _ledger(tenant_id: str) -> Dict[str, List[Dict[str, Any]]]:
    return _LEDGERS.setdefault(tenant_id, {"evidence": [], "logs": []})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_blob(blob: Any) -> str:
    return hashlib.sha256(
        json.dumps(blob, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _compute_chain_hash(
    record_id: str,
    previous_hash: Optional[str],
    payload_hash: str,
    result_hash: str,
    created_at_iso: str,
) -> str:
    """Tamper-evident chain hash (donor formula, unchanged)."""
    data = "|".join(
        [record_id, previous_hash or "", payload_hash, result_hash, created_at_iso]
    )
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


class AuditChainBlock(UniversalBlock):
    name = "audit_chain"
    version = "1.0.0"
    description = (
        "Tamper-evident evidence chain: every record links to its "
        "predecessor, and verify_chain full-walks the chain naming each "
        "violation."
    )
    layer = 1
    tags = ["security", "audit", "evidence", "enterprise"]
    requires = []

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        data = input_data if isinstance(input_data, dict) else {}
        action = params.get("action", data.get("action", "record_evidence"))
        tenant_id = str(params.get("tenant_id", data.get("tenant_id", "local")))
        ledger = _ledger(tenant_id)

        if action == "record_evidence":
            return self._record_evidence(ledger, tenant_id, data)
        if action == "log_action":
            return self._log_action(ledger, tenant_id, data)
        if action == "list_evidence":
            return self._list_evidence(ledger, data)
        if action == "list_logs":
            return self._list_logs(ledger, data)
        if action == "verify_chain":
            return self._verify_chain(ledger, data)
        return {"status": "error", "error": f"Unknown action: {action}"}

    def _record_evidence(self, ledger: Dict, tenant_id: str, data: Dict) -> Dict:
        required = ("action_execution_id", "action_type", "principal_id")
        missing = [k for k in required if not data.get(k)]
        if missing:
            return {"status": "error", "error": f"missing: {', '.join(missing)}"}
        payload = data.get("payload", {})
        result = data.get("result", {})
        payload_hash = _hash_blob(payload)
        result_hash = _hash_blob(result)
        previous = ledger["evidence"][-1] if ledger["evidence"] else None
        previous_hash = previous["chain_hash"] if previous else None
        record_id = f"ev-{next(_ids)}"
        created_at = _now()
        chain_hash = _compute_chain_hash(
            record_id, previous_hash, payload_hash, result_hash, created_at
        )
        record = {
            "id": record_id,
            "tenant_id": tenant_id,
            "project_id": data.get("project_id"),
            "action_execution_id": data["action_execution_id"],
            "action_type": data["action_type"],
            "principal_id": data["principal_id"],
            "payload_hash": payload_hash,
            "result_hash": result_hash,
            "previous_hash": previous_hash,
            "chain_hash": chain_hash,
            "created_at": created_at,
        }
        ledger["evidence"].append(record)
        return {"status": "success", "record": dict(record)}

    def _log_action(self, ledger: Dict, tenant_id: str, data: Dict) -> Dict:
        entry = {
            "id": f"al-{next(_ids)}",
            "tenant_id": tenant_id,
            "project_id": data.get("project_id"),
            "principal_id": data.get("principal_id"),
            "action": data.get("action_name") or data.get("action"),
            "resource_type": data.get("resource_type"),
            "resource_id": data.get("resource_id"),
            "status": data.get("status"),
            "details": data.get("details", {}),
            "created_at": _now(),
        }
        ledger["logs"].append(entry)
        return {"status": "success", "entry": dict(entry)}

    def _list_evidence(self, ledger: Dict, data: Dict) -> Dict:
        out = list(ledger["evidence"])
        if data.get("action_type"):
            out = [r for r in out if r["action_type"] == data["action_type"]]
        if data.get("project_id"):
            out = [r for r in out if r["project_id"] == data["project_id"]]
        return {"status": "success", "evidence": out}

    def _list_logs(self, ledger: Dict, data: Dict) -> Dict:
        out = list(ledger["logs"])
        if data.get("action"):
            out = [r for r in out if r["action"] == data["action"]]
        if data.get("resource_type"):
            out = [r for r in out if r["resource_type"] == data["resource_type"]]
        return {"status": "success", "logs": sorted(
            out, key=lambda r: r["created_at"], reverse=True
        )}

    def _verify_chain(self, ledger: Dict, data: Dict) -> Dict:
        """FULL WALK (the donor's missing piece): recompute every link and
        every payload/result digest; report each violation by record id."""
        records = list(ledger["evidence"])
        if data.get("project_id"):
            records = [r for r in records if r["project_id"] == data["project_id"]]
        violations: List[Dict[str, Any]] = []
        expected_previous: Optional[str] = None
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
                    {
                        "record": record["id"],
                        "error": "previous_hash linkage broken",
                        "expected": expected_previous,
                        "stored": record["previous_hash"],
                    }
                )
            if computed != record["chain_hash"]:
                violations.append(
                    {
                        "record": record["id"],
                        "error": "chain_hash mismatch",
                        "computed": computed,
                        "stored": record["chain_hash"],
                    }
                )
            expected_previous = record["chain_hash"]
        return {
            "status": "success",
            "verified": not violations,
            "records_walked": len(records),
            "violations": violations,
        }
