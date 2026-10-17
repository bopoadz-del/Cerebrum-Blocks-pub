"""Approval Rules - the human step between a proposed clearance rule and a
number an engineer will move a duct to satisfy, ported from <private-repo>
``app/rules/approval.py``.

A candidate rule is inert. It is stored, it is listed, it can be read - and
it cannot reach the rule table until a named person approves that specific
rule, by id. Approving a batch, approving by count, approving anything the
reviewer has not looked at individually: none of those exist here, because a
clearance figure is exactly the kind of thing that gets waved through when
the interface makes it easy to.

Every approval and every rejection is a ledger row. The question an engineer
will eventually ask about a rule is not "is it approved" but "who approved
it, when, and against what text", and only the ledger can answer that.

The donor writes its ledger rows through a SQLAlchemy session
(``app/ledger.record``). This block keeps approvals in-process with the
donor's exact semantics: everything arrives pending, decisions are one at a
time by id with a named reviewer, an anonymous approval is refused, and
every decision appends a ledger row with actor, states and clause text.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List

from app.core.universal_base import UniversalBlock

STATUS_PENDING = "pending_approval"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"


def _envelope(status, result=None, error=None, detail=None):
    return {
        "block_id": "approval_rules",
        "status": status,
        "result": result,
        "error": error,
        "detail": detail,
    }


class ApprovalRulesBlock(UniversalBlock):
    """Clearance-rule candidate approval gate, ported from <private-repo>."""

    name = "approval_rules"
    version = "1.0.0"
    description = (
        "real (clone of <private-repo> app/rules/approval.py): extracted "
        "clearance-rule candidates are inert until a NAMED reviewer approves "
        "them one at a time by id - no approve_all, no approval by count; an "
        "anonymous approval is refused and every decision is a ledger row "
        "(who, when, against what text). approved_rules() only returns what a "
        "person individually approved, in the kit loader's shape. Ledger kept "
        "in-process; the donor's SQLAlchemy session is not ported."
    )
    layer = 3
    tags = ["bim", "approval", "rules", "governance", "bim-manager"]
    requires = []

    default_config = {}

    ui_schema = {
        "input": {
            "type": "json",
            "placeholder": '{"action": "decide", "project_id": "p1", "source_doc": "spec.pdf", "rule_id": "SPEC-GAS-LV-400", "approve": true, "reviewer": "an engineer"}',
            "multiline": True,
        },
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "result", "type": "json", "label": "Result"}]},
    }

    def __init__(self, hal_block=None, config: Dict[str, Any] = None):
        super().__init__(hal_block=hal_block, config=config)
        # key: (project_id, source_doc) -> {"candidates": [...], }
        self._sets: Dict[tuple, Dict[str, Any]] = {}
        self._ledger: List[Dict[str, Any]] = []

    # -- donor Candidate / CandidateSet semantics -------------------------
    @staticmethod
    def _candidate(rule_id: str, payload: dict) -> Dict[str, Any]:
        return {
            "rule_id": rule_id,
            "rule": dict(payload),
            "status": STATUS_PENDING,
            "decided_by": None,
            "decided_at": None,
            "note": None,
        }

    @staticmethod
    def _as_dict(candidate: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "rule_id": candidate["rule_id"],
            "status": candidate["status"],
            "decided_by": candidate["decided_by"],
            "decided_at": candidate["decided_at"],
            "note": candidate["note"],
            "rule": candidate["rule"],
        }

    def _from_extraction(
        self, project_id: str, source_doc: str, extracted: list
    ) -> List[Dict[str, Any]]:
        """Wrap extractor output. Everything arrives pending; nothing arrives
        applied."""
        return [
            self._candidate(str(r.get("rule_id") or f"CANDIDATE-{i}"), dict(r))
            for i, r in enumerate(extracted)
        ]

    def _approved_rules(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """The approved candidates, in the shape the kit's loader accepts."""
        out = []
        for candidate in candidates:
            if candidate["status"] != STATUS_APPROVED:
                continue
            payload = candidate["rule"]
            source = payload.get("source") or {
                "doc": payload.get("source_doc", ""),
                "clause": payload.get("source_clause", ""),
                "text_hash": payload.get("source_text_hash", ""),
            }
            out.append(
                {
                    "rule_id": candidate["rule_id"],
                    "system_a": payload["system_a"],
                    "system_b": payload["system_b"],
                    "min_gap_mm": float(payload["min_gap_mm"]),
                    "axis": payload.get("axis", "any"),
                    "precedence": payload.get("precedence", "project_spec"),
                    "source": source,
                }
            )
        return out

    def _decide(
        self,
        candidates: List[Dict[str, Any]],
        rule_id: str,
        approve: bool,
        reviewer: str,
        project_id: str,
        source_doc: str,
        note: str | None = None,
    ) -> Dict[str, Any]:
        """Approve or reject exactly one candidate, and write it to the ledger.

        One at a time, by id, with a name attached. There is deliberately no
        ``approve_all``: the reviewer has to have looked at the clause.
        """
        if not reviewer or not reviewer.strip():
            raise _NotApproved("an approval must name the person making it")

        candidate = next((c for c in candidates if c["rule_id"] == rule_id), None)
        if candidate is None:
            raise _KeyError(rule_id)

        candidate["status"] = STATUS_APPROVED if approve else STATUS_REJECTED
        candidate["decided_by"] = reviewer.strip()
        candidate["decided_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        candidate["note"] = note

        self._ledger.append(
            {
                "entity": "rule_candidate",
                "entity_id": rule_id[:32],
                "from_state": STATUS_PENDING,
                "to_state": candidate["status"],
                "actor": candidate["decided_by"],
                "payload": {
                    "project_id": project_id,
                    "source_doc": source_doc,
                    "rule_id": rule_id,
                    "clause": candidate["rule"].get("source_clause")
                    or (candidate["rule"].get("source") or {}).get("clause"),
                    "min_gap_mm": candidate["rule"].get("min_gap_mm"),
                    "note": note,
                },
            }
        )
        return candidate

    # -- block surface ----------------------------------------------------
    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "")).lower()
        try:
            if action == "ingest":
                return self._ingest(payload)
            if action == "decide":
                return self._do_decide(payload)
            if action == "approved":
                return self._approved(payload)
            if action == "list":
                return self._list(payload)
            if action == "ledger":
                return _envelope("ok", {"ledger": list(self._ledger), "count": len(self._ledger)})
            return _envelope(
                "error", error=f"unknown action: {action or '(none)'}",
                detail={"known": ["ingest", "decide", "approved", "list", "ledger"]},
            )
        except _NotApproved as exc:
            return _envelope("refused", error=str(exc))
        except _KeyError as exc:
            return _envelope(
                "refused",
                error=f"no candidate with rule_id {exc.args[0]!r}; decisions are "
                "by id, one at a time, and only existing candidates can be decided",
            )
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=f"{type(exc).__name__}: {exc}")

    def _ingest(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        project_id = str(payload.get("project_id") or "")
        source_doc = str(payload.get("source_doc") or "")
        extracted = payload.get("extracted") or []
        if not project_id or not source_doc:
            return _envelope(
                "refused",
                error="ingest needs a project_id and a source_doc; a candidate "
                "set without a source document has no text to approve against",
            )
        candidates = self._from_extraction(project_id, source_doc, extracted)
        self._sets[(project_id, source_doc)] = candidates
        return _envelope(
            "ok",
            {
                "project_id": project_id,
                "source_doc": source_doc,
                "candidates": [self._as_dict(c) for c in candidates],
            },
        )

    def _do_decide(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        project_id = str(payload.get("project_id") or "")
        source_doc = str(payload.get("source_doc") or "")
        rule_id = str(payload.get("rule_id") or "")
        candidates = self._sets.get((project_id, source_doc))
        if candidates is None:
            return _envelope(
                "refused",
                error=f"no candidate set for project {project_id!r} doc {source_doc!r}; "
                "ingest first, and nothing can be approved without a source document",
            )
        if not rule_id:
            return _envelope("refused", error="a decision must name the rule_id being decided")
        candidate = self._decide(
            candidates,
            rule_id,
            bool(payload.get("approve")),
            str(payload.get("reviewer") or ""),
            project_id,
            source_doc,
            note=payload.get("note"),
        )
        return _envelope("ok", self._as_dict(candidate))

    def _approved(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        project_id = str(payload.get("project_id") or "")
        source_doc = str(payload.get("source_doc") or "")
        candidates = self._sets.get((project_id, source_doc))
        if candidates is None:
            return _envelope(
                "refused",
                error=f"no candidate set for project {project_id!r} doc {source_doc!r}",
            )
        return _envelope("ok", {"rules": self._approved_rules(candidates)})

    def _list(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        project_id = str(payload.get("project_id") or "")
        rows = []
        for (pid, doc), candidates in self._sets.items():
            if project_id and pid != project_id:
                continue
            rows.append(
                {
                    "project_id": pid,
                    "source_doc": doc,
                    "candidates": [self._as_dict(c) for c in candidates],
                }
            )
        return _envelope("ok", {"sets": rows})


class _NotApproved(Exception):
    """Raised when unapproved candidates are asked to behave like rules, or an
    approval cannot name the person making it."""


class _KeyError(Exception):
    """Raised when a decision names a rule_id that is not among the candidates."""
