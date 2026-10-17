# Ported (real) from <private-repo>:
#   app/monitors/base.py          - three-valued monitor contract (Check /
#     MonitorResult / aggregate / unprovable_across / run_all)
#   app/review_package.py         - verification_of / enrich_change_set /
#     annotate_bcf (carries the verified-vs-conditional distinction into the
#     deliverables)
#   app/review.py                 - approve / reject / edit decision rules
#     (the apply_review discipline: approve refuses while unacknowledged
#     unprovable checks remain; reject reopens eligible clashes; edit maps a
#     re-monitored verdict to verified / verified_conditional / escalated).
#
# The SQLAlchemy zone/clash ledger is not ported: the review ledger is
# in-process and the monitor implementations remain the caller's (the same
# scope zone_arbitration documents). The verdict math and the deliverable
# enrichment are carried verbatim.

"""Monitor contract.

Three monitors run after every proposal and all three must pass before anything
is committed. They are deliberately separate rather than one big check, because
they fail for different reasons and a reviewer needs to see which one objected:
"this move solves the clash but pushes a duct into the next zone" and "this move
solves the clash but reverses the fall on a drain" are different conversations.

A monitor returns a result, never a bare boolean. A bare boolean cannot say what
it looked at, and a monitor whose reasoning is not recorded is a monitor nobody
can argue with -- which is worse than no monitor at all, because it carries
authority it has not earned.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

PASS = "pass"
FAIL = "fail"
UNPROVABLE = "unprovable"


@dataclass
class Check:
    """One sub-question inside a monitor.

    ``status`` is three-valued on purpose. ``unprovable`` means the model does
    not carry the data the check needs -- no ports, no access table. That is not
    a pass and must never be recorded as one; it is a statement that this
    particular assurance is absent from this run.
    """

    name: str
    status: str
    detail: str
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        return self.status == FAIL


#: A monitor's verdict. Three-valued for the same reason a check is.
VERDICT_PASS = "pass"
VERDICT_CONDITIONAL = "conditional"
VERDICT_FAIL = "fail"


@dataclass
class MonitorResult:
    """One monitor's verdict over its checks.

    ``verdict`` is the answer; ``passed`` is a narrow convenience that means
    *fully* passed and nothing else. An earlier version had only ``passed``, and
    returned True whenever no check had failed — so a monitor whose connectivity
    and access checks were both ``unprovable`` reported a pass, the resolver
    committed on it, and the distinction survived only as a sentence in
    ``reason`` that nothing read.

    On the one real building model available, every element lacks ports and no
    access table exists, so that path was not an edge case: it was every
    proposal. "Nothing failed" was being shown to reviewers as "everything
    passed", which is the precise substitution this class exists to prevent.
    """

    monitor: str
    verdict: str
    reason: str
    checks: list[Check] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """True only when every check actually passed."""
        return self.verdict == VERDICT_PASS

    @property
    def conditional(self) -> bool:
        """No check failed, and at least one could not be checked at all."""
        return self.verdict == VERDICT_CONDITIONAL

    @property
    def failed(self) -> bool:
        return self.verdict == VERDICT_FAIL

    @property
    def acceptable(self) -> bool:
        """Nothing objected. Not the same as everything having been verified."""
        return self.verdict in (VERDICT_PASS, VERDICT_CONDITIONAL)

    @property
    def unprovable_checks(self) -> list[str]:
        return [c.name for c in self.checks if c.status == UNPROVABLE]

    def as_dict(self) -> dict[str, Any]:
        return {
            "monitor": self.monitor,
            "verdict": self.verdict,
            "passed": self.passed,
            "reason": self.reason,
            "checks": [asdict(c) for c in self.checks],
            "unprovable": self.unprovable_checks,
            "evidence": self.evidence,
        }

    @classmethod
    def from_checks(
        cls, monitor: str, checks: list[Check], evidence: dict[str, Any] | None = None
    ) -> MonitorResult:
        failures = [c for c in checks if c.failed]
        if failures:
            reason = "; ".join(f"{c.name}: {c.detail}" for c in failures)
            return cls(monitor, VERDICT_FAIL, reason, checks, evidence or {})

        unprovable = [c.name for c in checks if c.status == UNPROVABLE]
        if unprovable:
            reason = (
                "nothing objected, but this model cannot answer: "
                + ", ".join(unprovable)
            )
            return cls(monitor, VERDICT_CONDITIONAL, reason, checks, evidence or {})

        return cls(monitor, VERDICT_PASS, "all checks passed", checks, evidence or {})


@dataclass
class MonitorContext:
    """Everything the monitors need to judge one proposed move."""

    model: Any
    element_gid: str
    vector_mm: tuple[float, float, float]
    zone_key: str
    zone_gids: list[str]
    buffer_gids: list[str]
    neighbour_zone_gids: dict[str, list[str]]
    rules: list[Any]
    access_rules: list[Any] = field(default_factory=list)
    store: Any = None
    stream: str | None = None
    baseline: dict[str, Any] = field(default_factory=dict)

    def element(self) -> Any:
        return self.model.element(self.element_gid)


class Monitor:
    """Base class. Subclasses implement :meth:`run` and nothing else."""

    name = "monitor"

    def run(self, ctx: MonitorContext) -> MonitorResult:
        raise RuntimeError(f"{type(self).__name__} does not implement run()")


def aggregate(results: dict[str, MonitorResult]) -> str:
    """The verdict over a whole monitor set.

    ``fail`` if any monitor objected. ``pass`` only if every monitor fully
    passed. ``conditional`` in between — nothing objected, but something could
    not be checked, and a caller must not be able to spend that as a pass.
    """
    if any(r.failed for r in results.values()):
        return VERDICT_FAIL
    if all(r.passed for r in results.values()):
        return VERDICT_PASS
    return VERDICT_CONDITIONAL


def unprovable_across(results: dict[str, MonitorResult]) -> list[str]:
    """Every check the model could not answer, as ``monitor.check``."""
    return sorted(
        f"{name}.{check}"
        for name, result in results.items()
        for check in result.unprovable_checks
    )


def run_all(monitors: list[Monitor], ctx: MonitorContext) -> tuple[str, dict[str, MonitorResult]]:
    """Run every monitor and return the aggregate verdict with the results.

    Every monitor runs even after one has failed. A resolver that retries needs
    the full objection list, not just the first complaint -- otherwise it fixes
    the boundary problem, resubmits, and only then discovers the gravity problem
    that was there all along, burning an attempt from a cap of three.

    Returns the verdict as a string rather than a boolean on purpose. The
    boolean version of this function silently merged "verified" with "nothing
    objected", and every caller inherited the merge.
    """
    results = {m.name: m.run(ctx) for m in monitors}
    return aggregate(results), results


"""Carry the verification distinction into the deliverables.

The kit writes `change_set.json` and the BCF package, and it does not know about
conditional verification — that concept belongs to this service, which is what
runs the monitors. So the kit writes its output and this module adds one thing to
it: whether each entry was fully verified, or accepted with checks this model
could not answer, and which checks those were.

It matters most here. A change set is what leaves the building: it is emailed,
imported into Revit, worked from on site. If the distinction lives only in the
service's database, then the moment the deliverable is exported it becomes
indistinguishable from a fully verified one, and every downstream reader is told
something stronger than what was measured.

Nothing under `vendor/` is edited. The kit's files are read back and enriched.
"""
import json
import shutil
import tempfile
import uuid
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

FULL = "full"
CONDITIONAL = "conditional"

#: What a reader is being told, in the deliverable itself.
VERIFICATION_NOTE = {
    FULL: "Every check of all three monitors passed against this model.",
    CONDITIONAL: (
        "No monitor objected, but this model could not answer the checks listed in "
        "unprovable_checks. Those are not passes. An engineer accepting this entry "
        "is accepting them."
    ),
}


def verification_of(proposal: Any) -> str:
    verdict = getattr(proposal, "verdict", "")
    return CONDITIONAL if verdict == "verified_conditional" else FULL


def enrich_change_set(path: str | Path, by_clash: dict[str, dict[str, Any]]) -> Path:
    """Add verification status to every entry the kit wrote.

    ``by_clash`` maps clash_key to ``{"verification": ..., "unprovable_checks": [...]}``.
    """
    p = Path(path)
    payload = json.loads(p.read_text(encoding="utf-8"))

    conditional = 0
    for entry in payload.get("entries", []):
        info = by_clash.get(entry.get("clash_id"), {})
        verification = info.get("verification", FULL)
        entry["verification"] = verification
        entry["unprovable_checks"] = info.get("unprovable_checks", [])
        entry["verification_note"] = VERIFICATION_NOTE[verification]
        if verification == CONDITIONAL:
            conditional += 1

    total = len(payload.get("entries", []))
    payload["verification_summary"] = {
        "entries": total,
        "fully_verified": total - conditional,
        "conditionally_verified": conditional,
        "note": (
            "A conditionally verified entry is one no monitor objected to and that "
            "this model could not fully check. Read unprovable_checks on each before "
            "applying it."
        ),
    }
    p.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return p


def annotate_bcf(path: str | Path, by_pair: dict[frozenset, dict[str, Any]]) -> Path:
    """Add a verification comment to every BCF topic.

    A ``Comment`` is standard BCF 2.1, so this survives into any viewer that
    reads the format rather than being an out-of-band note only this service
    understands.

    ``by_pair`` maps a frozenset of the two element GlobalIds to the same shape
    ``enrich_change_set`` takes.
    """
    p = Path(path)
    if not p.exists():
        return p

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        with zipfile.ZipFile(p) as zf:
            zf.extractall(work)

        for markup in sorted(work.rglob("markup.bcf")):
            try:
                tree = ET.parse(markup)
            except ET.ParseError:
                continue
            root = tree.getroot()

            # The kit puts both element GlobalIds in the topic title, which is
            # the one place they appear without re-parsing the viewpoint.
            title = root.findtext("./Topic/Title") or ""
            info = next(
                (v for k, v in by_pair.items() if all(gid and gid in title for gid in k)),
                None,
            )
            if info is None:
                continue

            verification = info.get("verification", FULL)
            text = VERIFICATION_NOTE[verification]
            unprovable = info.get("unprovable_checks") or []
            if unprovable:
                text += " Not checkable here: " + ", ".join(unprovable) + "."

            comment = ET.SubElement(root, "Comment", {"Guid": str(uuid.uuid4())})
            ET.SubElement(comment, "Date").text = (
                root.findtext("./Topic/CreationDate") or ""
            )
            ET.SubElement(comment, "Author").text = "mep-judge"
            ET.SubElement(comment, "Comment").text = f"Verification: {verification}. {text}"
            tree.write(markup, encoding="UTF-8", xml_declaration=True)

        rebuilt = work.parent / "rebuilt.bcfzip"
        with zipfile.ZipFile(rebuilt, "w", zipfile.ZIP_DEFLATED) as zf:
            for item in sorted(work.rglob("*")):
                if item.is_file():
                    zf.write(item, item.relative_to(work).as_posix())
        shutil.move(str(rebuilt), str(p))
    return p

# ---------------------------------------------------------------------------
# Store block facade (the review decision discipline from app/review.py)
# ---------------------------------------------------------------------------

import json as _json
from pathlib import Path as _Path
from typing import Dict

from app.core.universal_base import UniversalBlock

# The clash states the reviewer may act on (from the donor's CLASH_STATES use).
_APPROVABLE_STATES = {"verified", "verified_conditional"}
_REJECTABLE_STATES = {"verified", "verified_conditional", "proposed"}


def _envelope(status, result=None, error=None, detail=None):
    return {"block_id": "mep_review_ledger", "status": status, "result": result, "error": error, "detail": detail}


class MepReviewLedgerBlock(UniversalBlock):
    """MEP review decisions + verification carry-through ported from <private-repo>."""

    name = "mep_review_ledger"
    version = "1.0.0"
    description = (
        "real: MEP review discipline ported from <private-repo> "
        "app/review.py (approve/reject/edit rules), app/review_package.py "
        "(verification_of / enrich_change_set / annotate_bcf) and "
        "app/monitors/base.py (three-valued monitor contract: fail > "
        "conditional > pass, never conflating \"nothing objected\" with "
        "\"everything passed\"). Approve refuses while unacknowledged "
        "unprovable checks remain; reject reopens eligible clashes; edit maps "
        "a re-monitored verdict to verified / verified_conditional / "
        "escalated. In-process ledger; monitor implementations are the "
        "caller's (same scope as zone_arbitration)."
    )
    layer = 3
    tags = ["bim", "mep", "review", "verification", "three-valued", "ledger", "bim-manager"]
    requires = []

    default_config = {}

    ui_schema = {
        "input": {"type": "json", "placeholder": '{"action": "approve", "clashes": [{"id": "c1", "state": "verified_conditional", "unprovable_checks": ["boundary.ports"]}], "acknowledge_unprovable": []}', "multiline": True},
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "result", "type": "json", "label": "Result"}]},
    }

    def __init__(self, hal_block=None, config: Dict[str, Any] = None):
        super().__init__(hal_block=hal_block, config=config)
        self._clashes: Dict[str, Dict[str, Any]] = {}
        self._reviews: list = []

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "aggregate")).lower()
        try:
            if action == "aggregate":
                return self._aggregate(payload)
            if action == "unprovable_across":
                return self._unprovable_across(payload)
            if action == "load_clashes":
                return self._load_clashes(payload)
            if action == "approve":
                return self._approve(payload)
            if action == "reject":
                return self._reject(payload)
            if action == "edit":
                return self._edit(payload)
            if action == "enrich_change_set":
                return self._enrich(payload)
            if action == "annotate_bcf":
                return self._annotate_bcf(payload)
            if action == "verification_of":
                return self._verification_of(payload)
            if action == "list_reviews":
                return _envelope("ok", {"reviews": list(self._reviews), "count": len(self._reviews)})
            return _envelope("error", error=f"unknown action: {action}", detail={"known": ["aggregate", "unprovable_across", "load_clashes", "approve", "reject", "edit", "enrich_change_set", "annotate_bcf", "verification_of", "list_reviews"]})
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data, params=None):
        return await self.process(input_data, params)

    # -- monitor contract --------------------------------------------------

    def _result_from_raw(self, raw: Dict[str, Any]) -> MonitorResult:
        checks = [Check(name=c["name"], status=c["status"], detail=c.get("detail", ""), data=c.get("data") or {}) for c in (raw.get("checks") or [])]
        return MonitorResult(monitor=str(raw.get("monitor", "")), verdict=str(raw.get("verdict", "")), reason=str(raw.get("reason", "")), checks=checks, evidence=raw.get("evidence") or {})

    def _aggregate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        raw = payload.get("results")
        if not isinstance(raw, list) or not raw:
            return _envelope("error", error="aggregate requires a 'results' list of monitor results")
        results = {r["monitor"]: self._result_from_raw(r) for r in raw if isinstance(r, dict)}
        verdict = aggregate(results)
        unprovable = unprovable_across(results)
        return _envelope("ok", {"verdict": verdict, "unprovable_checks": unprovable, "monitors": sorted(results)})

    def _unprovable_across(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        raw = payload.get("results")
        if not isinstance(raw, list):
            return _envelope("error", error="unprovable_across requires a 'results' list")
        results = {r["monitor"]: self._result_from_raw(r) for r in raw if isinstance(r, dict)}
        return _envelope("ok", {"unprovable_checks": unprovable_across(results)})

    # -- review decisions --------------------------------------------------

    def _load_clashes(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        clashes = payload.get("clashes")
        if not isinstance(clashes, list):
            return _envelope("error", error="load_clashes requires a 'clashes' list")
        for c in clashes:
            if not isinstance(c, dict):
                continue
            cid = str(c.get("id", ""))
            self._clashes[cid] = {
                "id": cid,
                "state": str(c.get("state", "proposed")),
                "unprovable_checks": [str(u) for u in (c.get("unprovable_checks") or [])],
            }
        return _envelope("ok", {"loaded": len(self._clashes)})

    def _unacknowledged(self, acknowledge: list) -> list:
        """Unanswered checks on approvable conditional proposals that were not named."""
        named = {str(a) for a in acknowledge}
        outstanding: list = []
        for clash in self._clashes.values():
            if clash["state"] != "verified_conditional":
                continue
            outstanding.extend(c for c in clash["unprovable_checks"] if c not in named)
        return sorted(set(outstanding))

    def _approve(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        acknowledge = [str(a) for a in (payload.get("acknowledge_unprovable") or [])]
        missing = self._unacknowledged(acknowledge)
        if missing:
            return _envelope(
                "refused",
                error="this zone holds proposals every monitor accepted but could not fully check. Approving them means accepting the checks this model cannot answer. List each one in acknowledge_unprovable.",
                detail={"unacknowledged": missing},
            )
        approved_fully = approved_conditionally = 0
        merged: list = []
        for clash in self._clashes.values():
            if clash["state"] not in _APPROVABLE_STATES:
                continue
            conditional = clash["state"] == "verified_conditional"
            clash["state"] = "merged"
            merged.append(clash["id"])
            if conditional:
                approved_conditionally += 1
            else:
                approved_fully += 1
        review = {
            "decision": "approve",
            "clashes_merged": len(merged),
            "approved_fully": approved_fully,
            "approved_conditionally": approved_conditionally,
            "acknowledged": acknowledge,
        }
        self._reviews.append(review)
        return _envelope("ok", {"review": review})

    def _reject(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        reopened: list = []
        notes = str(payload.get("notes", ""))
        for clash in self._clashes.values():
            if clash["state"] not in _REJECTABLE_STATES:
                continue
            clash["state"] = "open"
            reopened.append(clash["id"])
        review = {"decision": "reject", "clashes_reopened": len(reopened), "notes": notes}
        self._reviews.append(review)
        return _envelope("ok", {"review": review})

    def _edit(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        edits = payload.get("edits")
        if not isinstance(edits, list) or not edits:
            return _envelope("refused", error="an edit decision must carry at least one edit")
        out: list = []
        for edit in edits:
            if not isinstance(edit, dict):
                continue
            edit_verdict = str(edit.get("verdict", ""))
            unprovable = [str(u) for u in (edit.get("unprovable_checks") or [])]
            objections = [str(o) for o in (edit.get("objections") or [])]
            # The donor re-runs the reviewer's vector through all monitors and
            # maps: fail -> escalated, all-pass -> verified, else conditional.
            mapped = (
                "verified"
                if edit_verdict == VERDICT_PASS
                else "rejected"
                if edit_verdict == VERDICT_FAIL
                else "verified_conditional"
            )
            out.append({
                "clash_id": str(edit.get("clash_id", "")),
                "verdict": edit_verdict if edit_verdict else mapped,
                "passed": edit_verdict == VERDICT_PASS,
                "unprovable_checks": unprovable,
                "objections": objections,
            })
        review = {"decision": "edit", "edits": len(out)}
        self._reviews.append(review)
        return _envelope("ok", {"review": review, "edits": out})

    # -- deliverable enrichment --------------------------------------------

    def _enrich(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        change_set = payload.get("change_set")
        if not isinstance(change_set, dict):
            return _envelope("error", error="enrich_change_set requires a 'change_set' object")
        by_clash = payload.get("by_clash")
        if not isinstance(by_clash, dict):
            return _envelope("error", error="enrich_change_set requires a 'by_clash' map")
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = _Path(tmp) / "change_set.json"
            path.write_text(_json.dumps(change_set), encoding="utf-8")
            enrich_change_set(path, by_clash)
            enriched = _json.loads(path.read_text(encoding="utf-8"))
        return _envelope("ok", {"change_set": enriched})

    def _annotate_bcf(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        path = payload.get("path")
        if not path or not _Path(path).exists():
            return _envelope("error", error="annotate_bcf requires an existing 'path' to a BCF zip")
        by_pair: dict = {}
        raw_pairs = payload.get("by_pair")
        if isinstance(raw_pairs, list):
            for entry in raw_pairs:
                if isinstance(entry, dict) and isinstance(entry.get("gids"), list):
                    by_pair[frozenset(str(g) for g in entry["gids"])] = {k: v for k, v in entry.items() if k != "gids"}
        elif isinstance(raw_pairs, dict):
            by_pair = {frozenset(k if isinstance(k, list) else [k]): v for k, v in raw_pairs.items()}
        result = annotate_bcf(path, by_pair)
        return _envelope("ok", {"path": str(result)})

    def _verification_of(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        class _Probe:
            def __init__(self, verdict):
                self.verdict = verdict

        verdict = str(payload.get("verdict", ""))
        return _envelope("ok", {"verification": verification_of(_Probe(verdict))})
