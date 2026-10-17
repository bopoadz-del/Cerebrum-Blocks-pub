"""Evidence Chain — tamper-evident SHA-256 hash chain with a full-walk
verifier, ported from <private-repo> ``audit/service.py``.

The donor computed per-record chain hashes but never walked the chain;
the plan required adding the missing full walk. This block does both:
``record`` appends a chain-linked evidence record, ``verify`` walks the
ENTIRE chain and refuses on the first broken link, ``get_latest`` reads
the head. The chain store is in-process (honest about it).
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, List, Optional

from app.core.universal_base import UniversalBlock


def _envelope(status: str, result: Any = None, error: str = None, detail: Any = None) -> Dict[str, Any]:
    return {"block_id": "evidence_chain", "status": status, "result": result, "error": error, "detail": detail}


def _hash_blob(blob: Any) -> str:
    return hashlib.sha256(json.dumps(blob, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _compute_chain_hash(record_id: str, previous_hash: Optional[str], payload_hash: str, result_hash: str, created_at_iso: str) -> str:
    data = "|".join([record_id, previous_hash or "", payload_hash, result_hash, created_at_iso])
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


class EvidenceChainBlock(UniversalBlock):
    """Tamper-evident evidence chain with a full-walk verifier."""

    name = "evidence_chain"
    version = "1.0.0"
    description = (
        "Tamper-evident SHA-256 evidence chain ported from <private-repo> "
        "audit/service.py with the missing full-walk verifier added: record, "
        "verify (walks every link), get_latest. Chain store is in-process."
    )
    layer = 3
    tags = ["audit", "evidence", "hash-chain", "governance", "finance_ops"]
    requires = []

    default_config = {}

    ui_schema = {
        "input": {"type": "json", "placeholder": '{"action": "record", "tenant_id": "t1", "action_type": "journal_post", "principal_id": "u1", "payload": {}, "result": {}}', "multiline": True},
        "output": {"type": "json", "fields": [
            {"name": "status", "type": "string", "label": "Status"},
            {"name": "result", "type": "json", "label": "Result"},
            {"name": "error", "type": "string", "label": "Error"},
        ]},
    }

    def __init__(self, hal_block=None, config: Dict[str, Any] = None):
        super().__init__(hal_block=hal_block, config=config)
        self._chain: List[Dict[str, Any]] = []

    async def process(self, input_data: Any, params: Dict = None) -> Dict[str, Any]:
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "record")).lower()
        try:
            if action == "record":
                return self._record(payload)
            if action == "verify":
                return self._verify_chain(payload)
            if action == "get_latest":
                if self._chain:
                    return _envelope("ok", {"record": self._chain[-1]})
                return _envelope("ok", {"record": None})
            return _envelope(
                "error", error=f"unknown action: {action}",
                detail={"known": ["record", "verify", "get_latest"]},
            )
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data: Any, params: Dict = None) -> Dict[str, Any]:
        return await self.process(input_data, params)

    # -- internals ---------------------------------------------------------

    def _record(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        tenant_id = str(payload.get("tenant_id", ""))
        action_type = str(payload.get("action_type", ""))
        principal_id = str(payload.get("principal_id", ""))
        if not (tenant_id and action_type and principal_id):
            return _envelope("error", error="tenant_id, action_type and principal_id are required")
        payload_blob = payload.get("payload", {})
        result_blob = payload.get("result", {})
        created_at_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        record_id = f"ev-{len(self._chain) + 1}-{int(time.time() * 1000)}"
        previous_hash = self._chain[-1]["chain_hash"] if self._chain else None
        record = {
            "id": record_id,
            "tenant_id": tenant_id,
            "action_type": action_type,
            "principal_id": principal_id,
            "payload_hash": _hash_blob(payload_blob),
            "result_hash": _hash_blob(result_blob),
            "previous_hash": previous_hash,
            "created_at": created_at_iso,
        }
        record["chain_hash"] = _compute_chain_hash(
            record_id, previous_hash, record["payload_hash"], record["result_hash"], created_at_iso
        )
        self._chain.append(record)
        return _envelope("ok", {"record": record})

    def _verify_chain(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Full walk: recompute every link; refuse at the first broken one."""
        if not self._chain:
            return _envelope("ok", {"intact": True, "walked": 0})
        for i, record in enumerate(self._chain):
            expected_previous = self._chain[i - 1]["chain_hash"] if i > 0 else None
            if record.get("previous_hash") != expected_previous:
                return _envelope(
                    "refused",
                    error=f"integrity verification failed: chain broken at {record['id']}",
                    detail={"id": record["id"], "chain_broken": True, "walked": i},
                )
            recomputed = _compute_chain_hash(
                record["id"],
                record.get("previous_hash"),
                record["payload_hash"],
                record["result_hash"],
                record["created_at"],
            )
            if recomputed != record["chain_hash"]:
                return _envelope(
                    "refused",
                    error=f"integrity verification failed: tampered record {record['id']}",
                    detail={"id": record["id"], "chain_broken": True, "walked": i},
                )
        return _envelope("ok", {"intact": True, "walked": len(self._chain)})
