"""Insurance Compliance - deterministic coverage checks for marketplace work.

The trust layer's coverage gate: each vertical (task, order, trip,
transaction) declares required coverage lines; a provider's policies are
checked against them (validity window via caller-supplied dates, line
match), gaps are reported explicitly, and incidents are taken in with the
coverage verdict attached. Pure decision block: no network, no filesystem,
no wall clock - dates arrive in the payload, so every verdict is
reproducible.

Fail-closed: an expired or missing policy is a gap, never silently covered.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from app.core.universal_base import UniversalBlock
from app.core.http_errors import error_kind

# Required coverage lines per vertical preset.
REQUIRED_COVERAGE: Dict[str, List[str]] = {
    "task": ["public_liability", "property_damage"],
    "order": ["public_liability", "goods_in_transit"],
    "trip": ["auto_liability", "passenger_injury"],
    "transaction": ["public_liability"],
}


def parse_iso(value: Any, field: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{field}: ISO date string required")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{field}: invalid ISO date")


class InsuranceComplianceBlock(UniversalBlock):
    """Deterministic per-vertical coverage verification and incident intake."""

    name = "insurance_compliance"
    version = "1.0.0"
    description = (
        "Deterministic marketplace insurance gate: per-vertical required "
        "coverage lines, policy validity windows, explicit gap reporting, "
        "and incident intake with the coverage verdict attached."
    )
    layer = 3
    tags = ["domain", "marketplace", "insurance", "compliance", "trust", "deterministic"]
    requires: List[str] = []
    author = "Cerebrum Team"
    default_config: Dict[str, Any] = {}
    ui_schema = {
        "input": {"type": "json"},
        "output": {"type": "json"},
        "params": [],
        "quick_actions": [],
    }

    def __init__(self, hal_block=None, config: Dict = None):
        super().__init__(hal_block, config)
        # provider_id -> [policy records]
        self.policies: Dict[str, List[Dict[str, Any]]] = {}
        # incident_id -> record
        self.incidents: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------ api
    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        data = input_data if isinstance(input_data, dict) else {}
        merged = {**params, **data}
        operation = merged.get("operation") or merged.get("action") or "verify_coverage"

        try:
            if operation == "register_policy":
                return self._register_policy(merged)
            if operation == "verify_coverage":
                return self._verify_coverage(merged)
            if operation == "required_coverage":
                return self._required_coverage(merged)
            if operation == "incident_intake":
                return self._incident_intake(merged)
        except ValueError as exc:
            return {"status": "error", "error": str(exc), "error_kind": error_kind(exc), "operation": operation}

        return {
            "status": "error",
            "error": f"Unknown operation: {operation}",
            "available_operations": [
                "register_policy", "verify_coverage", "required_coverage", "incident_intake",
            ],
        }

    # -------------------------------------------------------------- helpers
    def _require(self, data: Dict[str, Any], keys: List[str]) -> Optional[str]:
        for key in keys:
            value = data.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                return key
        return None

    # ----------------------------------------------------------- operations
    def _register_policy(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["provider_id", "policy_id", "line", "valid_from", "valid_to"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        try:
            valid_from = parse_iso(data["valid_from"], "valid_from")
            valid_to = parse_iso(data["valid_to"], "valid_to")
        except ValueError as exc:
            return {"status": "error", "error": str(exc), "error_kind": error_kind(exc)}
        if valid_to < valid_from:
            return {"status": "error", "error": "valid_to before valid_from"}
        record = {
            "policy_id": data["policy_id"],
            "line": data["line"],
            "valid_from": valid_from.isoformat(),
            "valid_to": valid_to.isoformat(),
        }
        bucket = self.policies.setdefault(data["provider_id"], [])
        if any(p["policy_id"] == data["policy_id"] for p in bucket):
            return {"status": "error", "error": "policy_already_registered"}
        bucket.append(record)
        return {
            "status": "success",
            "operation": "register_policy",
            "provider_id": data["provider_id"],
            "policy_id": data["policy_id"],
        }

    def _verify_coverage(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["provider_id", "vertical", "as_of"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        required = REQUIRED_COVERAGE.get(data["vertical"])
        if required is None:
            return {
                "status": "error",
                "error": f"vertical: must be one of {sorted(REQUIRED_COVERAGE.keys())}",
            }
        try:
            as_of = parse_iso(data["as_of"], "as_of")
        except ValueError as exc:
            return {"status": "error", "error": str(exc), "error_kind": error_kind(exc)}

        covered: List[str] = []
        gaps: List[Dict[str, Any]] = []
        for line in required:
            candidates = [
                p for p in self.policies.get(data["provider_id"], [])
                if p["line"] == line
            ]
            active = [
                p for p in candidates
                if date.fromisoformat(p["valid_from"]) <= as_of <= date.fromisoformat(p["valid_to"])
            ]
            if active:
                covered.append(line)
            else:
                gaps.append({
                    "line": line,
                    "reason": "missing" if not candidates else "expired_or_not_yet_valid",
                })
        verdict = {
            "covered": not gaps,
            "vertical": data["vertical"],
            "as_of": as_of.isoformat(),
            "covered_lines": covered,
            "gaps": gaps,
        }
        return {"status": "success", "operation": "verify_coverage", **verdict}

    def _required_coverage(self, data: Dict[str, Any]) -> Dict[str, Any]:
        vertical = data.get("vertical")
        if vertical is None:
            return {
                "status": "success",
                "operation": "required_coverage",
                "requirements": {k: list(v) for k, v in REQUIRED_COVERAGE.items()},
            }
        required = REQUIRED_COVERAGE.get(vertical)
        if required is None:
            return {
                "status": "error",
                "error": f"vertical: must be one of {sorted(REQUIRED_COVERAGE.keys())}",
            }
        return {
            "status": "success",
            "operation": "required_coverage",
            "vertical": vertical,
            "required_lines": list(required),
        }

    def _incident_intake(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["incident_id", "provider_id", "vertical", "as_of", "severity"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        if data["severity"] not in ("low", "medium", "high", "critical"):
            return {"status": "error", "error": "severity: low|medium|high|critical"}
        existing = self.incidents.get(data["incident_id"])
        if existing is not None:
            return {**existing["public"], "idempotent": True}
        verdict = self._verify_coverage(
            {"provider_id": data["provider_id"], "vertical": data["vertical"], "as_of": data["as_of"]}
        )
        record = {
            "incident_id": data["incident_id"],
            "provider_id": data["provider_id"],
            "vertical": data["vertical"],
            "severity": data["severity"],
            "as_of": data["as_of"],
            "covered": verdict.get("covered", False),
            "gaps": verdict.get("gaps", []),
        }
        public = {
            "status": "success",
            "operation": "incident_intake",
            "incident_id": data["incident_id"],
            "covered": record["covered"],
            "gaps": record["gaps"],
            "severity": record["severity"],
        }
        record["public"] = public
        self.incidents[data["incident_id"]] = record
        return public
