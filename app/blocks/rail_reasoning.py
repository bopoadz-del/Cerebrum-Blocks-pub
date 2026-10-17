"""Railway & Metro Construction reasoning gate — store-facing wrapper, wired
to the shared kit_engine.

The gate itself is now declarative: app/blocks/rail/manifest.yaml (vocabulary)
plus invariants.yaml (records), evaluated by app.blocks.kit_engine — the same
evaluator airport_construction and datacentre declare against. Nothing in the
evaluator knows what a twist limit or a chainage is; this module is the HOST:
it builds Figure objects from the query/answer/qualifiers the caller supplies
(the portable spec's ``extract_figures``), calls the kit's hooks, and turns
the resulting Outcome(s) back into the block's verdict shape.

Four of the old six never-allowed derivations have no declarative home in
this engine (see app/blocks/rail/invariants.yaml's header comment and the
migration report) and are still evaluated here directly, against
app.blocks.rail.reasoning.DERIVATION_GUARD. So is the TBM chainage-band range
check (INV-5's other half): the engine's `band` kind is a fixed range per
KIT, declared once in invariants.yaml, not a dynamic range per FIGURE — and a
face-pressure schedule's chainage band varies per drive. Both are named
explicitly, not silently reinvented.

``gate_answer`` keeps its old signature exactly, so both the direct-call
tests and ``RailReasoningBlock.process()`` exercise the same code path — a
gutted ``process()`` still goes through the engine, and the engine cannot be
bypassed by calling the block instead of the function.
"""
from __future__ import annotations

import pathlib
import time
from typing import Any, Dict, List, Optional

from app.blocks.kit_engine import DisabledKit, Figure, KitLoadError, load_kit
from app.blocks.rail import reasoning
from app.blocks.rail.reasoning import TrackBasis, TrackState
from app.core.universal_base import UniversalBlock

_KIT_DIR = pathlib.Path(__file__).parent / "rail"

_kit_cache: Any = None


def _kit() -> Any:
    """Loaded once, fail-closed: a kit that does not parse refuses everything
    (app.blocks.kit_engine.DisabledKit) rather than degrading to no gate."""
    global _kit_cache
    if _kit_cache is None:
        try:
            _kit_cache = load_kit(_KIT_DIR)
        except KitLoadError as exc:
            _kit_cache = DisabledKit(name="rail", path=_KIT_DIR, reason=str(exc))
    return _kit_cache


def _first_number(text: str) -> Optional[float]:
    match = reasoning.NUMBER.search(text or "")
    return float(match.group(0).replace(",", "")) if match else None


# --------------------------------------------------------------------------
# extract_figures — the host builds Figures from the query/answer/qualifiers
# --------------------------------------------------------------------------

def _build_figures(
    query: str,
    answer: str,
    *,
    tier: Optional[str],
    line_speed: Optional[float],
    route: Optional[str],
    category: Optional[str],
    sft_verified_date: Optional[str],
    method: Optional[str],
    disturbed_since: Optional[bool],
    clearance: Optional[Dict[str, Any]],
    tbm: Optional[Dict[str, Any]],
) -> "tuple[List[Figure], bool]":
    combined = f"{query} {answer}"
    figures: List[Figure] = []
    live_state_classes_present = False

    def add(quantity: str, **kw: Any) -> None:
        kw.setdefault("origin", "tool")
        kw.setdefault("source_id", "answer-text")
        kw.setdefault("text", combined)
        figures.append(Figure(quantity=quantity, **kw))

    # ---- INV-1: geometry limits ------------------------------------------
    category_pair = len(reasoning.distinct_mentions(reasoning.CATEGORY_TOKEN, combined)) >= 2
    if (reasoning.GEOMETRY_LIMIT_WORDS.search(answer) and reasoning.NUMBER.search(answer)) or (
        category_pair and reasoning.CARRY_VERB.search(combined)
    ):
        has_number = bool(reasoning.NUMBER.search(answer))
        add(
            "geometry_limit",
            value=_first_number(answer) if has_number else None,
            unit="mm" if has_number else None,
            qualifiers={"tier": tier, "line_speed": line_speed, "category": category},
        )

    # ---- INV-2 / INV-3: SFT -----------------------------------------------
    if reasoning.SFT_WORDS.search(answer):
        add(
            "sft",
            value=_first_number(answer),
            unit="degC",
            qualifiers={
                "route": route,
                "SFT_verified_date": sft_verified_date,
                "method": method,
                "disturbed_since": disturbed_since,
            },
        )

    # ---- INV-3: buckling / stressing, not otherwise named -----------------
    if reasoning.BUCKLING_WORDS.search(answer):
        add("buckling_answer", qualifiers={"disturbed_since": disturbed_since})

    # ---- INV-3: handback speed --------------------------------------------
    if reasoning.HANDBACK_SPEED_WORDS.search(answer):
        add(
            "handback_speed",
            value=_first_number(answer),
            unit="mph",
            qualifiers={"disturbed_since": disturbed_since},
        )
        live_state_classes_present = True

    # ---- INV-4: clearance / gauging ---------------------------------------
    if reasoning.CLEARANCE_WORDS.search(answer) and reasoning.NUMBER.search(answer):
        supplied = clearance or {}
        add(
            "clearance_envelope",
            value=_first_number(answer),
            unit="mm",
            qualifiers={
                "envelope_type": supplied.get("envelope_type"),
                "cant": supplied.get("cant"),
                "curve_radius": supplied.get("curve_radius"),
                "line_speed": line_speed,
            },
        )

    # ---- INV-5 (qualifier half): TBM face pressure -------------------------
    if reasoning.FACE_PRESSURE_WORDS.search(combined):
        supplied = tbm or {}
        add(
            "face_pressure",
            value=_first_number(answer),
            unit="bar",
            qualifiers={
                "chainage_min_m": supplied.get("chainage_min_m"),
                "chainage_max_m": supplied.get("chainage_max_m"),
                "ground_basis": supplied.get("ground_basis"),
            },
        )

    # ---- settlement/movement trigger — never carried between assets -------
    asset_pair = len(reasoning.distinct_mentions(reasoning.ASSET_TOKEN, combined)) >= 2
    if reasoning.TRIGGER_WORDS.search(combined) or (asset_pair and reasoning.CARRY_VERB.search(combined)):
        has_trigger_word = bool(reasoning.TRIGGER_WORDS.search(combined))
        add(
            "trigger_level",
            value=_first_number(answer) if has_trigger_word else None,
            unit="mm" if has_trigger_word else None,
        )

    # ---- TSR — only the current notice proves what is in force ------------
    if reasoning.TSR_WORDS.search(combined):
        add("tsr_speed", value=_first_number(answer), unit="mph")
        live_state_classes_present = True

    # ---- ballast — staleness: any disturbance invalidates it ---------------
    if reasoning.BALLAST_WORDS.search(combined):
        add("ballast_depth", value=_first_number(answer), unit="mm")

    # ---- track geometry recording -------------------------------------------
    if reasoning.GEOMETRY_RECORDING_WORDS.search(combined):
        add("geometry_recording")

    # ---- catch-all live-state question with no other named figure ---------
    needs_live_state = bool(reasoning.LIVE_STATE_WORDS.search(combined))
    if needs_live_state and not live_state_classes_present:
        add("live_state_answer")

    return figures, needs_live_state


# --------------------------------------------------------------------------
# the evidence standard (REJECT_AS_PROOF), as the authority ladder (H1)
# --------------------------------------------------------------------------

_CLAIM_QUANTITY_WORDS = (
    ("handback_speed", reasoning.HANDBACK_SPEED_WORDS),
    ("tsr_speed", reasoning.TSR_WORDS),
    ("face_pressure", reasoning.FACE_PRESSURE_WORDS),
    ("clearance_envelope", reasoning.CLEARANCE_WORDS),
    ("sft", reasoning.SFT_WORDS),
)


def _classify_claim(query: str, answer: str) -> Optional[str]:
    text = f"{query} {answer}"
    for quantity, pattern in _CLAIM_QUANTITY_WORDS:
        if pattern.search(text):
            return quantity
    return None


def _resolve_source_class(kit: Any, citation: str) -> Optional[str]:
    for name, spec in kit.manifest.source_classes.items():
        if spec.matches(citation):
            return name
    return None


def _build_evidence_figures(kit: Any, query: str, answer: str, evidence: List[str]) -> List[Figure]:
    quantity = _classify_claim(query, answer)
    if not quantity or not evidence:
        return []
    figures = []
    for citation in evidence:
        figures.append(Figure(
            quantity=quantity,
            origin="document",
            source_id=citation,
            source_class=_resolve_source_class(kit, citation),
            text=citation,
        ))
    return figures


# --------------------------------------------------------------------------
# gate_answer — builds Figures, drives the engine, returns the old verdict
# shape. Kept as a module function (not only inside process()) so the direct
# AC-level tests exercise exactly what process() exercises.
# --------------------------------------------------------------------------

def gate_answer(
    query: str,
    answer: str,
    *,
    live_state: Optional[TrackState] = None,
    tier: Optional[str] = None,
    line_speed: Optional[float] = None,
    route: Optional[str] = None,
    category: Optional[str] = None,
    sft_verified_date: Optional[str] = None,
    method: Optional[str] = None,
    disturbed_since: Optional[bool] = None,
    clearance: Optional[Dict[str, Any]] = None,
    tbm: Optional[Dict[str, Any]] = None,
    chainage_m: Optional[float] = None,
    evidence: Optional[List[str]] = None,
    retrieval: Optional[Any] = None,
) -> Dict[str, Any]:
    """Gate one answer through the shared kit_engine.

    ``retrieval``, when supplied, lets a caller prove the scope refusal fires
    BEFORE any retrieval happens: this function never calls it — the scope
    check (H0) returns first, and nothing downstream is reached.
    """
    kit = _kit()
    query = query or ""
    answer = answer or ""
    combined = f"{query} {answer}"
    evidence = list(evidence or [])

    # ---- H0: scope, before anything else -----------------------------------
    scope_outcome = kit.pre_retrieval(query)
    if scope_outcome.verdict == "refused":
        return {"verdict": "refused", "blocked_reason": scope_outcome.blocked_reason}

    block_messages: List[str] = []

    # ---- the four never-declarative derivation-guard entries (host-side) --
    for name, pattern, reason in reasoning.DERIVATION_GUARD:
        if pattern.search(combined):
            block_messages.append(f"{reason} [{name}]")

    figures, needs_live_state = _build_figures(
        query, answer,
        tier=tier, line_speed=line_speed, route=route, category=category,
        sft_verified_date=sft_verified_date, method=method,
        disturbed_since=disturbed_since, clearance=clearance, tbm=tbm,
    )

    # ---- INV-5's other half: a per-figure dynamic chainage band (host-side,
    # see the module docstring and invariants.yaml's INV-RAIL-5 note) --------
    if reasoning.FACE_PRESSURE_WORDS.search(combined):
        supplied = tbm or {}
        band_min, band_max = supplied.get("chainage_min_m"), supplied.get("chainage_max_m")
        if band_min is not None and band_max is not None and chainage_m is not None:
            if not (band_min <= chainage_m <= band_max):
                block_messages.append(
                    f"INV-5 violation: chainage {chainage_m}m is outside the "
                    f"scheduled band {band_min}-{band_max}m — a face pressure "
                    "schedule is chainage-specific, not route-wide"
                )

    live_disturbed = bool(live_state and live_state.track_disturbed_since() is not None)
    events = ["track_disturbed"] if (disturbed_since is True or live_disturbed) else []

    state: Dict[str, Any] = {"disturbance_record": {"as_of": time.time()}}
    if live_state is not None:
        if live_state.possession_system is not None:
            state["possession_system"] = {"as_of": live_state.fetched_at}
        if live_state.manual_log is not None:
            state["manual_log"] = {"as_of": live_state.fetched_at}

    outcome = kit.answer_time(figures, state=state, events=events)
    if outcome.blocked_reason:
        block_messages.append(outcome.blocked_reason)

    evidence_figures = _build_evidence_figures(kit, query, answer, evidence)
    if evidence_figures:
        ranking_outcome = kit.ranking(evidence_figures)
        if ranking_outcome.blocked_reason:
            block_messages.append(ranking_outcome.blocked_reason)

    if block_messages:
        return {"verdict": "block", "blocked_reason": "; ".join(block_messages)}

    result: Dict[str, Any] = {"verdict": "pass"}
    # Hard preconditions: possessions, isolations, TSRs in force and manual
    # protection are surfaced, never silently passed through as if the track
    # were clear. Not an invariant kind — it is supplementary information
    # attached on an otherwise-clean pass, not a violation of anything.
    if needs_live_state and live_state is not None:
        active = {
            "possessions": live_state.possessions_in_force(),
            "isolations": live_state.isolations_in_force(),
            "tsrs_in_force": live_state.tsrs_in_force(),
            "protection_arrangements": live_state.protection_arrangements(),
        }
        if any(active.values()):
            result["corrected"] = {"live_preconditions": active}
    return result


# --------------------------------------------------------------------------
# the store-facing block
# --------------------------------------------------------------------------

def _envelope(status, result=None, error=None, detail=None):
    return {
        "block_id": "rail_reasoning",
        "status": status,
        "result": result,
        "error": error,
        "detail": detail,
    }


class RailReasoningBlock(UniversalBlock):
    name = "rail_reasoning"
    version = "1.0.0"
    description = (
        "Deterministic Railway & Metro Construction reasoning gate, evaluated "
        "by the shared kit_engine against app/blocks/rail/manifest.yaml + "
        "invariants.yaml. Every statement passes INV-1 (geometry limit "
        "carries tier design|maintenance|safety AND line_speed), INV-2 (SFT "
        "carries route, verification date, method and disturbed_since), "
        "INV-3 (no buckling/stressing/handback-speed answer without the "
        "disturbance state), INV-4 (clearance carries envelope_type, "
        "line_speed, cant and curve_radius), INV-5 (TBM face pressure "
        "carries a chainage band, min AND max, and a ground/groundwater "
        "basis), the six never-allowed derivations, the possession/"
        "signalling + manual-log live-state gate, the evidence standard "
        "(authority ladder) and the staleness rules. Go/no-go questions are "
        "refused BEFORE retrieval. Blocked and refused statements fail loud; "
        "nothing is invented."
    )
    layer = 3
    tags = ["rail", "metro", "construction", "track", "grounding", "gate"]
    requires: list = []

    async def process(self, input_data: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            query = str(input_data.get("query") or params.get("query") or "").strip()
            answer = str(input_data.get("answer") or params.get("answer") or "").strip()
            if not query or not answer:
                return _envelope("refused", error="query and answer are required")

            raw_state = input_data.get("live_state")
            if raw_state is None:
                state = None
            elif isinstance(raw_state, TrackState):
                state = raw_state
            elif isinstance(raw_state, dict):
                state = TrackState(
                    possession_system=raw_state.get("possession_system"),
                    manual_log=raw_state.get("manual_log"),
                    fetched_at=raw_state.get("fetched_at"),
                )
            else:
                return _envelope(
                    "refused",
                    error="live_state must be {possession_system, manual_log, fetched_at}",
                )

            evidence = input_data.get("evidence") or []
            if isinstance(evidence, str):
                evidence = [evidence]

            verdict = gate_answer(
                query,
                answer,
                live_state=state,
                tier=input_data.get("tier"),
                line_speed=input_data.get("line_speed"),
                route=input_data.get("route"),
                category=input_data.get("category"),
                sft_verified_date=input_data.get("SFT_verified_date") or input_data.get("sft_verified_date"),
                method=input_data.get("method"),
                disturbed_since=input_data.get("disturbed_since"),
                clearance=input_data.get("clearance"),
                tbm=input_data.get("tbm"),
                chainage_m=input_data.get("chainage_m"),
                evidence=list(evidence),
            )
            basis = TrackBasis()
            verdict["interview_status"] = basis.interview_status
            verdict["unfilled_figures"] = basis.unfilled()
            return _envelope("success", result=verdict)
        except Exception as exc:  # noqa: BLE001 — a gate that dies silently is worse
            return _envelope("error", error=f"{type(exc).__name__}: {exc}")


__all__ = ["RailReasoningBlock", "gate_answer", "TrackBasis", "TrackState"]
