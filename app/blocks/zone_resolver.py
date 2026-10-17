"""Zone Resolver - the discipline that resolves one zone's clashes, ported
from <private-repo> ``app/agents/zone_resolver.py`` (ZoneResolver).

The monitor machinery is the product's; this block enforces the contract
the donor's resolver lives by:

1. Kit resolution order first (gravity last, so a drain is never asked to
   move), then worst-first within a rank.
2. Every candidate runs ALL monitors. Not one, not the cheap two - a
   candidate evaluated by fewer than the full declared set is refused,
   because a single skipped monitor is exactly the hole this discipline
   exists to close.
3. Commit only on a clean sweep; record the monitor evidence either way.
   A sweep with any unprovable check is ``verified_conditional`` - never
   spent as a verification, because a reviewer approving it is accepting
   the named gaps, not being told there were none.
4. After ``max_attempts`` (default 3, deliberately low - a resolver that
   grinds through forty candidates never reaches the ninety easy clashes)
   the clash is escalated with the alternatives tried and the named
   objections.
5. Boundary-owned clashes are NEVER committed here. The element is shared
   with a neighbouring zone; the proposal is handed to the coordinator
   with ``handed_to_coordinator=True`` and no commit record.

In-process: commits are recorded on the block instance, monitor verdicts
arrive in the payload as the caller's monitor set.
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence

from app.core.universal_base import UniversalBlock

VERDICT_VERIFIED = "verified"
VERDICT_CONDITIONAL = "verified_conditional"
VERDICT_REJECTED = "rejected"
VERDICT_ESCALATED = "escalated"
VERDICT_FLAGGED = "flagged_unsourced"

#: The donor's fixed monitor set (app/monitors/__init__.py ALL_MONITORS):
#: geometry, boundary, integrity - fixed and ordered. A declared override
#: may narrow it; it may never grow into "run whichever you like".
DEFAULT_MONITORS: List[str] = ["geometry", "boundary", "integrity"]

Vector3 = tuple[float, float, float]


def _envelope(status, result=None, error=None, detail=None):
    return {
        "block_id": "zone_resolver",
        "status": status,
        "result": result,
        "error": error,
        "detail": detail,
    }


def as_vector3(values: Sequence[float]) -> Vector3:
    """A checked 3-tuple. A move vector is always exactly three numbers."""
    x, y, z = (float(v) for v in values)
    return (x, y, z)


def _magnitude(vector: Sequence[float]) -> float:
    return sum(v * v for v in vector) ** 0.5


def _dominant_axis(vector: Sequence[float]) -> int:
    return max(range(3), key=lambda i: abs(vector[i]))


def _box_gap(box_a: Sequence[float], box_b: Sequence[float]) -> float:
    """Separation between two axis-aligned boxes, in metres. 0 if they overlap."""
    gaps = [
        max(0.0, max(box_a[i] - box_b[i + 3], box_b[i] - box_a[i + 3]))
        for i in range(3)
    ]
    return sum(g * g for g in gaps) ** 0.5


class ZoneResolverBlock(UniversalBlock):
    """One zone's resolver discipline, ported from <private-repo>."""

    name = "zone_resolver"
    version = "1.0.0"
    description = (
        "real (clone of <private-repo> app/agents/zone_resolver.py "
        "ZoneResolver): per-zone clash resolution with the donor's discipline - "
        "kit resolution order, every candidate runs ALL monitors (a candidate "
        "missing a declared monitor's verdict is refused), clean-sweep commit "
        "with verified vs verified_conditional separation, three-attempt cap "
        "escalating with named objections, and boundary-owned clashes handed to "
        "the coordinator, never committed on this zone's branch. The monitors "
        "themselves are the product's; this block enforces the resolver "
        "contract. In-process."
    )
    layer = 3
    tags = ["bim", "coordination", "resolver", "multi-zone", "bim-manager"]
    requires = []

    default_config = {}

    ui_schema = {
        "input": {
            "type": "json",
            "placeholder": '{"action": "resolve", "clash": {...}, "candidates": [...], "monitors": ["geometry","boundary","integrity"]}',
            "multiline": True,
        },
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "result", "type": "json", "label": "Result"}]},
    }

    def __init__(self, hal_block=None, config: Dict[str, Any] = None):
        super().__init__(hal_block=hal_block, config=config)
        self._committed: List[Dict[str, Any]] = []

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "")).lower()
        try:
            if action == "resolve":
                return self._resolve(payload)
            if action == "run":
                return self._run(payload)
            if action == "committed":
                return _envelope(
                    "ok", {"committed": list(self._committed), "count": len(self._committed)}
                )
            return _envelope(
                "error", error=f"unknown action: {action or '(none)'}",
                detail={"known": ["resolve", "run", "committed"]},
            )
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=f"{type(exc).__name__}: {exc}")

    # -- ordering ---------------------------------------------------------
    @staticmethod
    def _order_clashes(clashes: List[Dict[str, Any]], order: List[str]) -> List[Dict[str, Any]]:
        """Kit resolution order first, then worst-first within a rank."""

        def rank(c):
            systems = list(c.get("systems") or [])
            ranks = [
                order.index(s) if s in order else 99 for s in systems
            ] or [99]
            return (min(ranks), -float(c.get("severity_mm", 0.0) or 0.0), c.get("clash_key", ""))

        return sorted(clashes, key=rank)

    # -- candidate ordering ----------------------------------------------
    @staticmethod
    def _rank_candidates(
        candidates: List[Dict[str, Any]],
        element_bbox: Sequence[float] | None,
        partner_bbox: Sequence[float] | None,
        scope_bboxes: List[Sequence[float]],
        required_gap_mm: float,
    ) -> List[Dict[str, Any]]:
        """Order candidates by whether they can plausibly work, then by size.

        The kit orders by displacement alone, which is the right instinct and
        the wrong result under an attempt cap: a diagonal splits its
        displacement across two axes, so it separates less along the axis that
        is actually tight, and a unit diagonal sorts ahead of the axis move of
        the same size. With three monitored attempts, all three go to
        candidates that geometrically cannot achieve the gap.

        So each candidate is scored with a cheap bounding-box prediction
        first, and the ones that cannot reach the required separation are
        tried last rather than first. The prediction is not a verdict:
        whatever survives this ordering still goes through all the monitors.
        This only decides what to spend an attempt on.
        """
        if partner_bbox is None or not element_bbox or not partner_bbox:
            return candidates

        scope = []
        for box in scope_bboxes:
            if box:
                scope.append(box)

        required_m = float(required_gap_mm) / 1000.0
        scored = []
        for i, cand in enumerate(candidates):
            vector = as_vector3(cand["vector_mm"])
            moved = [element_bbox[j] + vector[j] / 1000.0 for j in range(3)] + [
                element_bbox[j + 3] + vector[j] / 1000.0 for j in range(3)
            ]
            achieves = _box_gap(moved, partner_bbox) + 1e-9 >= required_m
            collisions = sum(1 for box in scope if _box_gap(moved, box) <= 0.0)
            scored.append(
                (
                    0 if achieves else 1,
                    collisions,
                    _magnitude(vector),
                    i,
                    cand,
                )
            )

        scored.sort(key=lambda t: t[:4])
        return [cand for *_, cand in scored]

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def _pick_movable(
        clash: Dict[str, Any], elements: Dict[str, Dict[str, Any]]
    ) -> tuple[str | None, Dict[str, Any] | None]:
        """Prefer moving the element this zone owns, and never move structure."""
        owned = set(clash.get("zone_gids") or [])
        candidates = [clash.get("a_gid"), clash.get("b_gid")]
        ranked = sorted(
            (g for g in candidates if g),
            key=lambda g: (
                g not in owned,
                (elements.get(g) or {}).get("discipline", "") == "structural",
                bool((elements.get(g) or {}).get("is_gravity", False)),
            ),
        )
        for gid in ranked:
            el = elements.get(gid)
            if el is not None and el.get("discipline", "") != "structural":
                return gid, el
        return None, None

    def _aggregate(
        self, monitors: Dict[str, Dict[str, Any]], declared: List[str]
    ) -> tuple[str, Dict[str, Any], List[str]]:
        """All monitors, every candidate - none skipped, or the payload is
        refused before any attempt is spent."""
        missing = [m for m in declared if m not in monitors]
        if missing:
            raise _Refusal(
                f"candidate was not run through every monitor; missing: {missing}. "
                "A proposal is verified when all monitors pass, and any other "
                "combination is not a verified proposal."
            )
        failed = {name: r.get("reason") or "failed" for name, r in monitors.items()
                  if not r.get("passed")}
        unprovable = [name for name, r in monitors.items() if r.get("unprovable")]
        if failed:
            return "failed", failed, unprovable
        if unprovable:
            return "conditional", {}, unprovable
        return "pass", {}, unprovable

    # -- one clash --------------------------------------------------------
    def _resolve(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        clash = payload.get("clash")
        if not isinstance(clash, dict):
            return _envelope("refused", error="resolve needs a clash object")
        if not clash.get("id") or not clash.get("clash_key"):
            return _envelope(
                "refused", error="a clash needs an id and a clash_key to resolve"
            )
        owner = str(clash.get("owner", "zone"))
        if owner not in ("zone", "coordinator"):
            return _envelope(
                "refused",
                error=f"unknown clash owner {owner!r}; only 'zone' and 'coordinator' exist",
            )

        zone_key = str(payload.get("zone_key") or clash.get("zone_key") or "")
        declared = [str(m) for m in (payload.get("monitors") or DEFAULT_MONITORS)]
        candidates = [
            c for c in (payload.get("candidates") or []) if isinstance(c, dict)
        ]
        for cand in candidates:
            try:
                as_vector3(cand.get("vector_mm") or [])
            except (TypeError, ValueError) as exc:
                return _envelope(
                    "refused",
                    error=f"candidate vector must be exactly three numbers: {exc}",
                    detail={"candidate": cand.get("move_type")},
                )
        max_attempts = int(payload.get("max_attempts", 3) or 3)

        elements = payload.get("elements") or {}
        movable_gid, element = self._pick_movable(clash, elements)

        base: Dict[str, Any] = {
            "clash_id": clash.get("id"),
            "clash_key": clash.get("clash_key"),
            "element_gid": movable_gid or "",
            "move_type": "none",
            "vector_mm": [0.0, 0.0, 0.0],
            "verdict": VERDICT_ESCALATED,
            "attempt": 0,
            "monitors": {},
            "rule_ids": [],
            "clause_text": None,
            "committed_as": None,
            "handed_to_coordinator": False,
            "unprovable_checks": [],
            "alternatives": [],
            "rejected_attempts": [],
        }

        if element is None:
            base["alternatives"] = [
                {"reason": "neither element is present and movable in this zone"}
            ]
            return _envelope("ok", base)

        required_gap = float(clash.get("required_gap_mm", 0.0) or 0.0)
        rule_id = clash.get("rule_id")

        # A clearance clash with no rule behind it has no distance to move to.
        # It is flagged for an engineer, never dressed up as a proposal.
        if clash.get("kind") == "clearance" and not rule_id:
            base["verdict"] = VERDICT_FLAGGED
            base["alternatives"] = [
                {"reason": "clearance finding carries no sourced rule; no authorised distance exists"}
            ]
            return _envelope("ok", base)

        partner_gid = clash["b_gid"] if clash.get("a_gid") == movable_gid else clash.get("a_gid")
        partner = elements.get(partner_gid) or {}
        ranked = self._rank_candidates(
            candidates,
            element.get("bbox"),
            partner.get("bbox"),
            [
                (elements.get(g) or {}).get("bbox")
                for g in (clash.get("zone_gids") or [])
                if g not in (movable_gid, partner_gid)
            ],
            required_gap,
        )

        blocked_axes: set[tuple[int, int]] = set()
        tried: List[Dict[str, Any]] = []
        rejected_attempts: List[Dict[str, Any]] = []
        attempt = 0

        for cand in ranked:
            if attempt >= max_attempts:
                break

            vector = as_vector3(cand["vector_mm"])
            axis_sign = (_dominant_axis(vector), 1 if vector[_dominant_axis(vector)] > 0 else -1)
            if axis_sign in blocked_axes:
                # A previous attempt was rejected for pushing this way. Trying a
                # longer move along the same heading spends an attempt to be
                # told the same thing, harder.
                continue

            attempt += 1
            move_type = str(cand.get("move_type") or "translate")
            monitors = cand.get("monitors") or {}
            if not isinstance(monitors, dict):
                monitors = {}
            try:
                verdict, objections, unprovable = self._aggregate(monitors, declared)
            except _Refusal as refusal:
                return _envelope(
                    "refused",
                    error=str(refusal),
                    detail={"attempt": attempt, "move_type": move_type},
                )

            if verdict == "pass":
                proposal_verdict = VERDICT_VERIFIED
            elif verdict == "failed":
                proposal_verdict = VERDICT_REJECTED
            else:
                proposal_verdict = VERDICT_CONDITIONAL

            if verdict != "failed":
                out = dict(base)
                out.update(
                    {
                        "move_type": move_type,
                        "vector_mm": list(vector),
                        "verdict": proposal_verdict,
                        "attempt": attempt,
                        "monitors": monitors,
                        "rule_ids": [rule_id] if rule_id else [],
                        "unprovable_checks": unprovable,
                    }
                )
                out["rejected_attempts"] = rejected_attempts
                if owner == "coordinator":
                    # Verified locally, but the element is shared. The
                    # coordinator re-runs both zones before anything commits.
                    out["handed_to_coordinator"] = True
                    out["alternatives"] = tried
                    return _envelope("ok", out)
                commit_id = self._commit(movable_gid, vector, clash, zone_key)
                out["committed_as"] = commit_id
                out["alternatives"] = tried
                return _envelope("ok", out)

            rejected_attempts.append(
                {
                    "attempt": attempt,
                    "move_type": move_type,
                    "vector_mm": list(vector),
                    "monitors": monitors,
                }
            )
            tried.append(
                {
                    "attempt": attempt,
                    "move_type": move_type,
                    "vector_mm": [round(v, 1) for v in vector],
                    "displacement_mm": round(_magnitude(vector), 1),
                    "objections": objections,
                }
            )
            if "boundary" in objections:
                blocked_axes.add(axis_sign)

        base["attempt"] = attempt
        base["rule_ids"] = [rule_id] if rule_id else []
        base["alternatives"] = tried
        base["rejected_attempts"] = rejected_attempts
        base["element_gid"] = movable_gid
        return _envelope("ok", base)

    def _commit(
        self, gid: str, vector: Sequence[float], clash: Dict[str, Any], zone_key: str
    ) -> str | None:
        """In-process stand-in for the donor's branch commit (store.ensure_branch
        + store.commit on the zone's branch). The store block records the
        proposal; the branch itself is the product's."""
        record = {
            "zone_key": zone_key,
            "gid": gid,
            "vector_mm": list(as_vector3(vector)),
            "clash_key": clash.get("clash_key"),
            "rule_id": clash.get("rule_id"),
        }
        self._committed.append(record)
        return f"{zone_key}:{gid}:{clash.get('clash_key')}"

    # -- entry point ------------------------------------------------------
    def _run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        clashes = [c for c in (payload.get("clashes") or []) if isinstance(c, dict)]
        order = [str(s) for s in (payload.get("order") or [])]
        zone_key = str(payload.get("zone_key") or "")

        result = {
            "zone_key": zone_key,
            "clashes_seen": 0,
            "verified": 0,
            "verified_conditional": 0,
            "escalated": 0,
            "flagged_unsourced": 0,
            "handed_to_coordinator": 0,
            "outcomes": [],
        }
        for clash in self._order_clashes(clashes, order):
            outcome_env = self._resolve({"clash": clash, **{
                k: v for k, v in payload.items() if k not in ("clashes", "order", "action")
            }})
            if outcome_env["status"] != "ok":
                return outcome_env
            outcome = outcome_env["result"]
            result["outcomes"].append(outcome)
            result["clashes_seen"] += 1
            if outcome.get("handed_to_coordinator"):
                result["handed_to_coordinator"] += 1
            elif outcome.get("verdict") == VERDICT_VERIFIED:
                result["verified"] += 1
            elif outcome.get("verdict") == VERDICT_CONDITIONAL:
                result["verified_conditional"] += 1
            elif outcome.get("verdict") == VERDICT_FLAGGED:
                result["flagged_unsourced"] += 1
            else:
                result["escalated"] += 1
        return _envelope("ok", result)


class _Refusal(Exception):
    """Internal: payload broke the all-monitors contract; surface as refused."""
