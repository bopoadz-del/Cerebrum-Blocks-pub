"""Dispute Resolution - deterministic dispute lifecycle with evidence digests.

The marketplace trust layer: parties open disputes with evidence references
(digests owned by the evidence blocks - declared in requires), platform
resolves them with a recorded outcome, and every step lands in an auditable
history. Sequence-based deadlines (no wall clock): an unresolved dispute
auto-escalates after the caller-supplied step window.

Fail-closed: only the task parties may open or add evidence, only the
platform may resolve, resolutions must name a reason, and evidence entries
are deduplicated by digest.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.universal_base import UniversalBlock
from app.core.http_errors import error_kind

DISPUTE_STATES = ("open", "under_review", "resolved")
RESOLUTIONS = ("refunded", "released", "dismissed")
TERMINAL = {"refunded", "released", "dismissed"}


class DisputeResolutionBlock(UniversalBlock):
    """Deterministic dispute lifecycle with evidence digests and deadlines."""

    name = "dispute_resolution"
    version = "1.0.0"
    description = (
        "Deterministic marketplace dispute lifecycle: party-gated opening "
        "and evidence submission by digest, platform-only resolution with "
        "recorded reasoning, sequence-based auto-escalation deadlines, and "
        "an auditable history."
    )
    layer = 3
    tags = ["domain", "marketplace", "dispute", "trust", "deterministic"]
    requires = ["evidence_or_refuse"]
    author = "Cerebrum Team"
    default_config: Dict[str, Any] = {
        "escalate_after_steps": 100,
    }
    ui_schema = {
        "input": {"type": "json"},
        "output": {"type": "json"},
        "params": [],
        "quick_actions": [],
    }

    def __init__(self, hal_block=None, config: Dict = None):
        super().__init__(hal_block, config)
        # dispute_id -> record
        self.disputes: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------ api
    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        data = input_data if isinstance(input_data, dict) else {}
        merged = {**params, **data}
        operation = merged.get("operation") or merged.get("action") or "open"

        try:
            if operation == "open":
                return self._open(merged)
            if operation == "add_evidence":
                return self._add_evidence(merged)
            if operation == "escalate":
                return self._escalate(merged)
            if operation == "resolve":
                return self._resolve(merged)
            if operation == "status":
                return self._status(merged)
        except ValueError as exc:
            return {"status": "error", "error": str(exc), "error_kind": error_kind(exc), "operation": operation}

        return {
            "status": "error",
            "error": f"Unknown operation: {operation}",
            "available_operations": ["open", "add_evidence", "escalate", "resolve", "status"],
        }

    # -------------------------------------------------------------- helpers
    def _require(self, data: Dict[str, Any], keys: List[str]) -> Optional[str]:
        for key in keys:
            value = data.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                return key
        return None

    def _record(self, record: Dict[str, Any], event: str, extra: Dict[str, Any]) -> None:
        record["history"].append({"event": event, **extra})

    # ----------------------------------------------------------- operations
    def _open(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["dispute_id", "task_id", "claimant", "claim_type", "parties"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        parties = data["parties"]
        if not isinstance(parties, list) or len(parties) < 2:
            return {"status": "error", "error": "parties: at least two required"}
        if data["claimant"] not in parties:
            return {"status": "error", "error": "claimant_not_a_party"}
        existing = self.disputes.get(data["dispute_id"])
        if existing is not None:
            return {**existing["public"], "idempotent": True}
        record = {
            "dispute_id": data["dispute_id"],
            "task_id": data["task_id"],
            "claimant": data["claimant"],
            "claim_type": data["claim_type"],
            "parties": [p for p in parties],
            "evidence": [],
            "state": "open",
            "opened_step": data.get("step", 0),
            "history": [{"event": "open", "step": data.get("step", 0)}],
        }
        public = {
            "status": "success",
            "operation": "open",
            "dispute_id": data["dispute_id"],
            "task_id": data["task_id"],
            "state": "open",
        }
        record["public"] = public
        self.disputes[data["dispute_id"]] = record
        return public

    def _add_evidence(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["dispute_id", "party", "digest"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        record = self.disputes.get(data["dispute_id"])
        if record is None:
            return {"status": "error", "error": "dispute_not_found"}
        if data["party"] not in record["parties"]:
            return {"status": "error", "error": "party_not_in_dispute"}
        if record["state"] != "open":
            return {"status": "error", "error": f"evidence_closed: state={record['state']}"}
        digest = data["digest"]
        if any(e["digest"] == digest for e in record["evidence"]):
            return {"status": "error", "error": "evidence_already_submitted"}
        entry = {
            "digest": digest,
            "party": data["party"],
            "kind": data.get("kind") or "artifact",
            "step": data.get("step", 0),
        }
        record["evidence"].append(entry)
        self._record(record, "add_evidence", {"digest": digest, "party": data["party"]})
        return {
            "status": "success",
            "operation": "add_evidence",
            "dispute_id": data["dispute_id"],
            "evidence_count": len(record["evidence"]),
        }

    def _escalate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["dispute_id"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        record = self.disputes.get(data["dispute_id"])
        if record is None:
            return {"status": "error", "error": "dispute_not_found"}
        if record["state"] != "open":
            return {"status": "error", "error": f"cannot_escalate: state={record['state']}"}
        window = int(self.config.get("escalate_after_steps") or 100)
        step = data.get("step")
        elapsed = None
        if step is not None:
            try:
                elapsed = int(step) - int(record["opened_step"])
            except (TypeError, ValueError):
                return {"status": "error", "error": "step: must be an integer"}
            if elapsed <= window:
                return {
                    "status": "error",
                    "error": "escalate_too_early",
                    "elapsed_steps": elapsed,
                    "window_steps": window,
                }
        record["state"] = "under_review"
        self._record(record, "escalate", {"step": step})
        return {
            "status": "success",
            "operation": "escalate",
            "dispute_id": data["dispute_id"],
            "state": "under_review",
            "auto": step is None,
        }

    def _resolve(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["dispute_id", "platform", "resolution", "reason"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        if data["platform"] != "platform":
            return {"status": "error", "error": "resolver_not_platform"}
        if data["resolution"] not in RESOLUTIONS:
            return {
                "status": "error",
                "error": f"resolution: must be one of {list(RESOLUTIONS)}",
            }
        record = self.disputes.get(data["dispute_id"])
        if record is None:
            return {"status": "error", "error": "dispute_not_found"}
        if record["state"] == "resolved":
            return {"status": "error", "error": "dispute_already_resolved"}
        if not isinstance(data["reason"], str) or not data["reason"].strip():
            return {"status": "error", "error": "reason: non-empty string required"}
        record["state"] = "resolved"
        record["resolution"] = data["resolution"]
        self._record(record, "resolve", {"resolution": data["resolution"], "reason": data["reason"]})
        return {
            "status": "success",
            "operation": "resolve",
            "dispute_id": data["dispute_id"],
            "state": "resolved",
            "resolution": data["resolution"],
            "evidence_count": len(record["evidence"]),
        }

    def _status(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["dispute_id"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        record = self.disputes.get(data["dispute_id"])
        if record is None:
            return {"status": "error", "error": "dispute_not_found"}
        return {
            "status": "success",
            "operation": "status",
            "dispute_id": data["dispute_id"],
            "task_id": record["task_id"],
            "state": record["state"],
            "resolution": record.get("resolution"),
            "evidence_count": len(record["evidence"]),
            "history": record["history"],
        }
