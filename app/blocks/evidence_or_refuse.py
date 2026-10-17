"""Evidence-or-Refuse Gate — an answer's claims must carry evidence or the
answer is refused, ported from <private-repo>'s evidence-or-refuse pattern
(tests/integration/test_refusal.py).

Each claim maps to evidence items; a claim with no evidence is refused,
and the answer is only allowed when every claim is evidenced.
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.core.universal_base import UniversalBlock


def _envelope(status, result=None, error=None, detail=None):
    return {"block_id": "evidence_or_refuse", "status": status, "result": result, "error": error, "detail": detail}


class EvidenceOrRefuseBlock(UniversalBlock):
    """Evidence-or-refuse: unevidenced claims are refused, never answered."""

    name = "evidence_or_refuse"
    version = "1.0.0"
    description = (
        "Evidence-or-refuse gate ported from <private-repo>'s refusal pattern: every "
        "claim in an answer must carry evidence; a claim with no evidence is "
        "refused, and the answer is allowed only when all claims are evidenced."
    )
    layer = 3
    tags = ["evidence", "grounding", "refusal", "<private-repo>"]
    requires = []

    default_config = {}

    ui_schema = {
        "input": {"type": "json", "placeholder": '{"action": "judge", "claims": [{"id": "c1", "evidence": ["doc1#p2"]}, {"id": "c2", "evidence": []}]}', "multiline": True},
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "result", "type": "json", "label": "Result"}]},
    }

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "judge")).lower()
        try:
            if action == "judge":
                claims = payload.get("claims") or []
                if not isinstance(claims, list) or not claims:
                    return _envelope("error", error="claims must be a non-empty list")
                verdicts: List[Dict[str, Any]] = []
                refused: List[str] = []
                for claim in claims:
                    cid = str(claim.get("id", ""))
                    evidence = claim.get("evidence") or []
                    ok = bool(evidence)
                    verdicts.append({"id": cid, "evidenced": ok, "evidence_count": len(evidence)})
                    if not ok:
                        refused.append(cid)
                if refused:
                    return _envelope(
                        "refused",
                        error=f"claims without evidence: {', '.join(refused)}",
                        detail={"verdicts": verdicts, "refused": refused},
                    )
                return _envelope("ok", {"verdicts": verdicts, "allowed": True})
            return _envelope("error", error=f"unknown action: {action}", detail={"known": ["judge"]})
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data, params=None):
        return await self.process(input_data, params)
