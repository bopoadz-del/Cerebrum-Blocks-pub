"""Offshore marine operations reasoning layer — deterministic gate.

The reference pattern is the aviation grounding gate and the datacentre kit:
verdicts are pass / block / refused with a named reason, and a blocked
statement never reaches an answer. Everything here is offline-deterministic —
no model calls, no credentials, no network. Seed data comes from
manifest.yaml; anything the encoding sheet has not supplied is a gap
(KNOWN_GAPS.md), never invented. No interview has run, so every manifest value
is null: this layer refuses, it does not answer with figures it does not have.

Five invariants are ENFORCED, not documented:

  INV-1 BAND          lay tension / strain / stress are never returned
                      single-sided. A minimum AND a maximum, or nothing.
  INV-2 STATIC/DYNAMIC no allowable without static_or_dynamic AND the region
                      it applies to (overbend | sagbend | touchdown | none).
  INV-3 SPREAD-TYPE   no envelope figure without spread_type, and no figure
                      carried from one spread type to another.
  INV-4 CAPABILITY+LIVE no DP / station-keeping answer without a named
                      failure_case AND a live_state_ref.
  INV-5 FORECAST      no condition-vs-criterion comparison without
                      horizon_hours, confidence, operation_duration_hours,
                      contingency_hours and window_covers.

Plus the derivation guard (the inferences that are never allowed, each
blocking under its own name), the two-source live-state gate (vessel
monitoring AND manual log), the evidence standard (REJECT_AS_PROOF), the
staleness rules and the scope refusals — which classify BEFORE retrieval.

A single violation blocks the WHOLE answer. There is one verdict path and no
parameter, flag, config key or environment variable skips it.
"""
from __future__ import annotations

import pathlib
import re
import time
from typing import Any, Dict, List, Optional, Sequence

import yaml

_MANIFEST_PATH = pathlib.Path(__file__).parent / "design_basis.yaml"

#: Every figure carries these. A null VALUE is legal — the interview has not
#: run. A missing QUALIFIER is not: half-qualified is how a sagbend allowable
#: answers an overbend question.
MANDATORY_QUALIFIERS = (
    "value",
    "unit",
    "spread_type",
    "water_depth_range_m",
    "pipe_or_cable_spec",
    "static_or_dynamic",
    "region",
    "source",
    "analysis_rev",
    "sea_state_assumed",
    "scope",
    "date_recorded",
    "valid_until",
)

SPREAD_TYPES = ("s_lay", "j_lay", "reel_lay", "heavy_lift")
REGIONS = ("overbend", "sagbend", "touchdown", "none")
STATIC_OR_DYNAMIC = ("static", "dynamic")

#: Forecast comparisons need all five, or the comparison is not a comparison.
FORECAST_QUALIFIERS = (
    "horizon_hours",
    "confidence",
    "operation_duration_hours",
    "contingency_hours",
    "window_covers",
)


class ManifestError(ValueError):
    """A figure arrived without its mandatory qualifiers."""


class InstallationBasis:
    """The installation analysis basis, loaded from manifest.yaml.

    The loader is the first gate. It refuses at LOAD time — not at answer
    time — so a half-qualified figure cannot sit in the manifest waiting to be
    quoted. The refusal names the figure and every key it lacks.
    """

    def __init__(self, manifest_path: Optional[pathlib.Path] = None) -> None:
        path = manifest_path or _MANIFEST_PATH
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.source = raw.get("source")
        self.scope = raw.get("scope")
        self.interview_status = raw.get("interview_status")
        self._entries: Dict[str, Dict[str, Any]] = {}
        for name, entry in (raw.get("design_basis") or {}).items():
            if not isinstance(entry, dict):
                raise ManifestError(
                    f"manifest figure '{name}' is not a qualified entry; every "
                    f"figure is a mapping carrying {', '.join(MANDATORY_QUALIFIERS)}"
                )
            missing = [key for key in MANDATORY_QUALIFIERS if key not in entry]
            if missing:
                raise ManifestError(
                    f"manifest figure '{name}' is partially qualified — missing "
                    f"{', '.join(missing)}. A figure without its qualifiers cannot "
                    f"be quoted against any question"
                )
            self._entries[name] = dict(entry)

    def field(self, name: str) -> Dict[str, Any]:
        """Provenance record for one figure, qualifiers included."""
        return dict(self._entries[name])

    def fields(self) -> Dict[str, Dict[str, Any]]:
        return {name: dict(entry) for name, entry in self._entries.items()}

    def value(self, name: str) -> Any:
        return self._entries[name]["value"]

    def unfilled(self) -> List[str]:
        """Figures the interview has not filled. Everything, until it runs."""
        return sorted(n for n, e in self._entries.items() if e.get("value") is None)


class SpreadState:
    """Current spread state. Requires BOTH sources:

    - ``monitoring``: what the vessel monitors — DP/thruster status, tension,
      generators, references, position.
    - ``manual_log``: what monitoring does NOT see — manual isolations, valves
      operated, components racked out, and the AS-SET stinger configuration.

    Nominal stinger configuration is not as-set configuration. As-set is live
    state, and it belongs in the manual log.

    Monitoring is itself a single point of failure: if it is unreachable the
    spread state is UNKNOWN. There is no design-basis fallback for live state —
    a design figure presented as a current state is the failure this gate
    exists to stop.
    """

    _MAX_AGE_SECONDS = 3600

    def __init__(
        self,
        monitoring: Optional[Dict[str, Any]],
        manual_log: Optional[Dict[str, Any]],
        fetched_at: Optional[float] = None,
    ) -> None:
        self.monitoring = monitoring
        self.manual_log = manual_log
        self.fetched_at = fetched_at if fetched_at is not None else time.time()

    def both_sources_present(self) -> bool:
        return self.monitoring is not None and self.manual_log is not None

    def fresh(self) -> bool:
        return (time.time() - self.fetched_at) <= self._MAX_AGE_SECONDS

    def components_out(self) -> List[Dict[str, Any]]:
        return list((self.manual_log or {}).get("components_out") or [])

    def stinger_as_set(self) -> Optional[Dict[str, Any]]:
        return (self.manual_log or {}).get("stinger_as_set")

    def valve_operated_since(self) -> Optional[float]:
        return (self.manual_log or {}).get("valve_operated_at")

    def dp_failure_since(self) -> Optional[float]:
        monitoring = self.monitoring or {}
        return monitoring.get("thruster_or_gen_failure_at")


# --------------------------------------------------------------------------
# rule tables — from the sheet, fail closed, never invented
# --------------------------------------------------------------------------

#: Refusals classify BEFORE retrieval. These are named-person decisions: the
#: barge master, the OIM, the dive supervisor. The system will not emit them.
SCOPE_REFUSAL_PATTERNS: List[tuple] = [
    ("start the operation", re.compile(
        r"can\s+we\s+(?:start|begin|commence)\s+(?:the\s+)?"
        r"(?:lift|pull[-\s]?in|lay|lowering|installation)",
        re.IGNORECASE)),
    ("weather go/no-go", re.compile(
        r"is\s+the\s+weather\s+(?:ok|okay|good|acceptable|fine)|"
        r"are\s+we\s+(?:good|ok)\s+to\s+go\s+on\s+weather|"
        r"can\s+we\s+work\s+in\s+this\s+weather",
        re.IGNORECASE)),
    ("degraded DP operation", re.compile(
        r"can\s+we\s+(?:run|operate|continue|stay)\s+on\s+"
        r"(?:two|2|three|3|\w+)\s+thrusters|"
        r"can\s+we\s+(?:run|operate)\s+with\s+(?:a\s+)?thruster\s+(?:out|down)",
        re.IGNORECASE)),
    ("dive authorisation", re.compile(
        r"is\s+it\s+safe\s+to\s+dive|can\s+(?:we|the\s+divers?)\s+(?:go\s+)?"
        r"(?:dive|in\s+the\s+water)",
        re.IGNORECASE)),
    ("approach authorisation", re.compile(
        r"can\s+we\s+get\s+closer|can\s+we\s+(?:approach|come\s+alongside)"
        r"(?:\s+\w+)*\s*\?*$",
        re.IGNORECASE)),
]

BAND_FIGURE_WORDS = re.compile(
    r"lay\s+tension|top\s+tension|tension\s+(?:is|of|at)\s|"
    r"\bstrain\b|\bstress\b|bending\s+moment",
    re.IGNORECASE,
)

ALLOWABLE_WORDS = re.compile(
    r"allowable|permissible|limit\s+(?:is|of)|utilisation|utilization|code\s+check",
    re.IGNORECASE,
)

ENVELOPE_WORDS = re.compile(
    r"envelope|operating\s+window|operability|limiting\s+(?:sea\s+state|condition)",
    re.IGNORECASE,
)

DP_WORDS = re.compile(
    r"\bDP\b|dynamic\s+position\w*|station[-\s]?keep\w*|thruster|"
    r"capability\s+plot|footprint",
    re.IGNORECASE,
)

FORECAST_COMPARISON_WORDS = re.compile(
    r"forecast|weather\s+window|hs\s*(?:is|of|=|<|>)|"
    r"(?:within|inside|below|under|exceeds?|above)\s+(?:the\s+)?criteri\w*|"
    r"criteri\w*\s+(?:is|are)\s+(?:met|not\s+met|satisfied)",
    re.IGNORECASE,
)

LIVE_STATE_WORDS = re.compile(
    r"\bDP\b|dynamic\s+position\w*|station[-\s]?keep\w*|thruster|"
    r"current\s+(?:capability|state|status)|right\s+now|"
    r"stinger\s+(?:setting|configuration|radius)|spread\s+availab\w*|"
    r"impairment|isolation",
    re.IGNORECASE,
)

#: A range needs two numbers, or two named bounds. One number is not a band.
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
_BAND_MARKERS = re.compile(
    r"\bto\b|\bbetween\b|[-–—]|\bmin\w*\b.*\bmax\w*\b|\brange\b|±|\+/-",
    re.IGNORECASE,
)

_SPREAD_MENTION = re.compile(r"s[-_\s]?lay|j[-_\s]?lay|reel[-_\s]?lay|heavy[-_\s]?lift", re.IGNORECASE)
_REGION_MENTION = re.compile(r"overbend|sagbend|touchdown", re.IGNORECASE)
_STATIC_DYNAMIC_MENTION = re.compile(r"\bstatic\b|\bdynamic\b", re.IGNORECASE)

_FAILURE_CASE_MENTION = re.compile(
    r"intact|worst[-\s]?case\s+single\s+failure|single\s+failure|"
    r"thruster\s+(?:out|failure|loss)|generator\s+(?:out|failure|loss)|"
    r"WCSF|failure\s+case",
    re.IGNORECASE,
)

#: Never allowed. Each blocks under its own name — the reason says which
#: inference was attempted, because "blocked" alone teaches nobody anything.
DERIVATION_GUARD: List[tuple] = [
    (
        "depth-range extrapolation",
        re.compile(
            r"(?=.*(?:extrapolat|beyond|deeper\s+than|outside)\w*)"
            r"(?=.*(?:depth|water\s+depth|analysed\s+range|analyzed\s+range))",
            re.IGNORECASE),
        "never-allowed derivation: extrapolating beyond the analysed water-depth range",
    ),
    (
        "static-to-dynamic",
        re.compile(
            r"(?=.*\bstatic\b)(?=.*\bdynamic\b)"
            r"(?=.*(?:so|therefore|implies|apply|applies|use|same|equival))",
            re.IGNORECASE),
        "never-allowed derivation: applying a static allowable to a dynamic case",
    ),
    (
        "post-failure DP from intact plot",
        re.compile(
            r"(?=.*intact)(?=.*(?:thruster|generator)\s*(?:out|down|failure|lost))",
            re.IGNORECASE),
        "never-allowed derivation: reading post-failure DP capability off the intact plot",
    ),
    # NOTE: the cross-spread carry is NOT a regex. Two mentions of the SAME
    # spread is how a correct answer reads ("what tension on the S-lay?" /
    # "hold 780-900 kN on the s_lay spread"), and a pattern that counts
    # mentions blocks it. The carry is two DISTINCT spread types plus a carry
    # verb; see _cross_spread_carry.
    (
        "rigid envelope on flexible or cable",
        re.compile(
            r"(?=.*rigid)(?=.*(?:flexible|umbilical|cable))"
            r"(?=.*(?:envelope|allowable|apply|applies|same|use))",
            re.IGNORECASE),
        "never-allowed derivation: applying a rigid-pipe envelope to flexible or cable",
    ),
    (
        "crane SWL across configuration",
        re.compile(
            r"(?=.*(?:SWL|safe\s+working\s+load|lift\s+capacity))"
            r"(?=.*(?:configuration|radius|boom|different|another|other))",
            re.IGNORECASE),
        "never-allowed derivation: carrying crane SWL across configuration, radius or boom angle",
    ),
    (
        "sister-vessel carry",
        re.compile(
            r"sister\s+vessel|sister\s+ship|same\s+class\s+vessel|"
            r"identical\s+vessel",
            re.IGNORECASE),
        "VESSEL TRAP: a vessel-specific figure does not transfer to a sister vessel",
    ),
    (
        "depth-band carry",
        re.compile(
            r"(?=.*(?:route|depth\s+band|another\s+(?:depth|band|section)))"
            r"(?=.*(?:same|apply|applies|carry|reuse|use\s+the))",
            re.IGNORECASE),
        "never-allowed derivation: carrying a route or depth-band figure to another band",
    ),
    (
        "window without alpha",
        re.compile(
            r"(?=.*(?:weather\s+window|forecast\s+window))"
            r"(?=.*(?:no\s+alpha|without\s+alpha|alpha\s+not|unfactored|"
            r"raw\s+forecast))",
            re.IGNORECASE),
        "never-allowed derivation: a weather window without the alpha margin applied",
    ),
    (
        "mixed-source sea state",
        re.compile(
            r"(?=.*\bHs\b)(?=.*\bTp\b)"
            r"(?=.*(?:different\s+source|another\s+source|second\s+source|"
            r"other\s+forecast|two\s+forecasts))",
            re.IGNORECASE),
        "never-allowed derivation: combining Hs from one source with Tp from another",
    ),
]

#: What is NOT acceptable as proof, per claim class.
REJECT_AS_PROOF: Dict[str, List[str]] = {
    "lay_tension": [
        "different water depth", "another depth", "different pipe",
        "another pipe", "different vessel", "another vessel",
    ],
    "strain_allowable": ["static analysis", "static case", "region unnamed"],
    "dp_capability": ["intact capability plot", "intact plot"],
    "weather_criterion": ["hs alone", "significant wave height only", "hs only"],
    "stinger_setting": ["nominal configuration", "nominal setting", "nominal radius"],
    "spread_availability": ["mobilisation plan", "mobilization plan", "mob plan"],
}

CLAIM_CLASS_WORDS: List[tuple] = [
    ("dp_capability", re.compile(r"\bDP\b|station[-\s]?keep|thruster|capability\s+plot", re.IGNORECASE)),
    ("stinger_setting", re.compile(r"stinger", re.IGNORECASE)),
    ("spread_availability", re.compile(r"spread\s+availab|vessel\s+availab", re.IGNORECASE)),
    ("weather_criterion", re.compile(r"weather|sea\s+state|\bHs\b|\bTp\b|criteri", re.IGNORECASE)),
    ("strain_allowable", re.compile(r"strain|stress|allowable", re.IGNORECASE)),
    ("lay_tension", re.compile(r"tension", re.IGNORECASE)),
]


_SPREAD_TOKEN = re.compile(
    r"(s|j|reel)[-_\s]?lay|(heavy)[-_\s]?lift", re.IGNORECASE
)
_CARRY_VERB = re.compile(
    r"\bsame\b|\bapply\b|\bapplies\b|\bcarry\b|\breuse\b|\bas\s+well\b|"
    r"\buse\s+the\b|\bequivalent\b|\btransfer\b",
    re.IGNORECASE,
)


def spread_types_mentioned(text: str) -> List[str]:
    """Distinct spread types named in *text*, normalised to manifest spelling."""
    found = []
    for match in _SPREAD_TOKEN.finditer(text or ""):
        prefix = (match.group(1) or match.group(2) or "").lower()
        name = "heavy_lift" if prefix == "heavy" else f"{prefix}_lay"
        if name not in found:
            found.append(name)
    return found


def _cross_spread_carry(text: str) -> Optional[str]:
    """Two DISTINCT spread types plus a carry verb, or None.

    Naming one spread twice is what a correct answer looks like. Naming two and
    saying "the same" is the inference that is never allowed.
    """
    named = spread_types_mentioned(text)
    if len(named) >= 2 and _CARRY_VERB.search(text or ""):
        return " -> ".join(named[:2])
    return None


def _classify_claim(query: str, answer: str) -> Optional[str]:
    text = f"{query} {answer}"
    for claim_class, pattern in CLAIM_CLASS_WORDS:
        if pattern.search(text):
            return claim_class
    return None


def _is_band(text: str) -> bool:
    """Two numbers with a band marker between them, or it is not a band."""
    numbers = _NUMBER.findall(text)
    return len(numbers) >= 2 and bool(_BAND_MARKERS.search(text))


def _verdict(
    verdict: str,
    reason: str = "",
    corrected: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {"verdict": verdict}
    if verdict in ("block", "refused"):
        result["blocked_reason"] = reason
    if corrected is not None:
        result["corrected"] = corrected
    return result


# --------------------------------------------------------------------------
# the invariant pipeline — one path, no bypass
# --------------------------------------------------------------------------

def _evaluate_invariants(
    query: str,
    answer: str,
    live_state: Optional[SpreadState],
    spread_type: Optional[str],
    region: Optional[str],
    static_or_dynamic: Optional[str],
    failure_case: Optional[str],
    live_state_ref: Optional[str],
    forecast: Optional[Dict[str, Any]],
    evidence: List[str],
    retrieval: Optional[Any],
    analysis_changed_since: bool,
) -> Dict[str, Any]:
    combined = f"{query} {answer} {' '.join(evidence)}"

    # ---- scope refusals: classify BEFORE retrieval -----------------------
    # These are named-person decisions. Nothing is retrieved, so nothing can
    # be quoted back as if it authorised the decision.
    for label, pattern in SCOPE_REFUSAL_PATTERNS:
        if pattern.search(query):
            return _verdict(
                "refused",
                f"scope refusal ({label}): this is a named-person decision — "
                f"the barge master, OIM or dive supervisor holds it. The system "
                f"will not emit it, and nothing was retrieved",
            )

    # ---- live-state gate: two sources, both required ---------------------
    needs_live_state = bool(LIVE_STATE_WORDS.search(f"{query} {answer}"))
    degraded: List[Dict[str, Any]] = []
    if needs_live_state:
        if live_state is None:
            return _verdict(
                "block",
                "spread state UNKNOWN — vessel monitoring unreachable. Live "
                "state has no design-basis fallback: a design figure is not a "
                "current state",
            )
        if not live_state.both_sources_present() or not live_state.fresh():
            return _verdict(
                "block",
                "spread state unavailable — vessel monitoring AND manual log "
                "are both required; the manual log carries what monitoring "
                "cannot see (manual isolations, components out, as-set stinger)",
            )
        degraded = live_state.components_out()

    # ---- staleness -------------------------------------------------------
    if analysis_changed_since and re.search(
        r"installation\s+analys|lay\s+analys|analysis\s+says|per\s+the\s+analysis",
        combined, re.IGNORECASE,
    ):
        return _verdict(
            "block",
            "installation analysis is stale — the vessel, stinger, tensioner, "
            "pipe or route has changed since it was run; it cannot support a "
            "current figure",
        )
    if live_state is not None and live_state.valve_operated_since() is not None and re.search(
        r"impairment|isolation\s+status|system\s+(?:is\s+)?available", combined, re.IGNORECASE,
    ):
        return _verdict(
            "block",
            "impairment status is stale — a valve has been operated since it "
            "was recorded",
        )
    if live_state is not None and live_state.dp_failure_since() is not None and DP_WORDS.search(combined):
        return _verdict(
            "block",
            "DP capability figure is stale — a thruster, generator or reference "
            "has failed since it was established",
        )

    # ---- evidence standard: REJECT_AS_PROOF ------------------------------
    claim_class = _classify_claim(query, answer)
    for citation in evidence:
        lowered = citation.lower()
        evidence_class = None
        for cls, rejected in REJECT_AS_PROOF.items():
            if any(fragment in lowered for fragment in rejected):
                evidence_class = cls
                break
        if claim_class and evidence_class:
            if claim_class == evidence_class:
                return _verdict(
                    "block",
                    f"rejected proof: '{citation}' is not acceptable evidence "
                    f"for {claim_class} (REJECT_AS_PROOF)",
                )
            return _verdict(
                "block",
                f"evidence substitution: '{citation}' proves {evidence_class}, "
                f"not {claim_class}",
            )

    # ---- derivation guard ------------------------------------------------
    carried = _cross_spread_carry(combined)
    if carried:
        return _verdict(
            "block",
            "never-allowed derivation: carrying an envelope figure between "
            f"spread types ({carried}) [cross-spread envelope carry]",
        )
    for name, pattern, reason in DERIVATION_GUARD:
        if pattern.search(combined):
            return _verdict("block", f"{reason} [{name}]")

    # ---- INV-1 BAND ------------------------------------------------------
    # An ALLOWABLE is a ceiling: single-sided is what a limit looks like, and
    # INV-2 is the invariant that governs it. INV-1 governs a REPORTED tension,
    # strain or stress, which varies along the lay and is meaningless as one
    # number. Applying the band rule to allowables made INV-2 unreachable.
    if (
        BAND_FIGURE_WORDS.search(answer)
        and _NUMBER.search(answer)
        and not ALLOWABLE_WORDS.search(answer)
    ):
        if not _is_band(answer):
            return _verdict(
                "block",
                "INV-1 violation: single-sided figure. Lay tension, strain and "
                "stress are returned as a band — a minimum AND a maximum — or "
                "not at all",
            )

    # ---- INV-2 STATIC/DYNAMIC + REGION -----------------------------------
    if ALLOWABLE_WORDS.search(answer):
        has_case = static_or_dynamic in STATIC_OR_DYNAMIC or bool(
            _STATIC_DYNAMIC_MENTION.search(answer)
        )
        has_region = (region in REGIONS) or bool(_REGION_MENTION.search(answer))
        if not (has_case and has_region):
            return _verdict(
                "block",
                "INV-2 violation: allowable without static_or_dynamic and the "
                "region it applies to (overbend | sagbend | touchdown | none). "
                "A sagbend allowable does not answer an overbend question",
            )

    # ---- INV-3 SPREAD-TYPE -----------------------------------------------
    if ENVELOPE_WORDS.search(answer) or (
        BAND_FIGURE_WORDS.search(answer) and _NUMBER.search(answer)
    ):
        if spread_type not in SPREAD_TYPES and not _SPREAD_MENTION.search(answer):
            return _verdict(
                "block",
                "INV-3 violation: envelope figure without spread_type "
                "(s_lay | j_lay | reel_lay | heavy_lift). Spread type is part "
                "of the identity of the figure, not a label on it",
            )

    # ---- INV-4 DP CAPABILITY + LIVE --------------------------------------
    if DP_WORDS.search(f"{query} {answer}"):
        has_failure_case = bool(failure_case) or bool(_FAILURE_CASE_MENTION.search(answer))
        if not has_failure_case or not live_state_ref:
            missing = []
            if not has_failure_case:
                missing.append("failure_case")
            if not live_state_ref:
                missing.append("live_state_ref")
            return _verdict(
                "block",
                "INV-4 violation: DP / station-keeping answer without "
                + " and ".join(missing)
                + ". A capability figure with no failure case named is a number "
                "with no meaning",
            )

    # ---- INV-5 FORECAST --------------------------------------------------
    if FORECAST_COMPARISON_WORDS.search(f"{query} {answer}"):
        supplied = forecast or {}
        missing = [key for key in FORECAST_QUALIFIERS if supplied.get(key) is None]
        if missing:
            return _verdict(
                "block",
                "INV-5 violation: condition-vs-criterion comparison without "
                + ", ".join(missing)
                + ". A forecast compared to a criterion without a horizon, a "
                "confidence and a window that covers the operation plus "
                "contingency is not a comparison",
            )
        if supplied.get("window_covers") is False:
            return _verdict(
                "block",
                "INV-5 violation: the forecast window does not cover the "
                "operation duration plus contingency",
            )

    # ---- N+1 with one component out is N: surface it, never infer it -----
    if degraded:
        component = degraded[0].get("component", "unknown")
        since = degraded[0].get("since")
        now = live_state.fetched_at if live_state else time.time()
        seconds = max(0.0, float(now - since)) if since is not None else 0.0
        return _verdict(
            "pass",
            corrected={
                "redundancy": "N",
                "degraded_from": "N+1",
                "degraded_to": "N",
                "degraded_component": component,
                "time_in_degraded_seconds": seconds,
            },
        )

    return _verdict("pass")


def gate_answer(
    query: str,
    answer: str,
    *,
    live_state: Optional[SpreadState] = None,
    spread_type: Optional[str] = None,
    region: Optional[str] = None,
    static_or_dynamic: Optional[str] = None,
    failure_case: Optional[str] = None,
    live_state_ref: Optional[str] = None,
    forecast: Optional[Dict[str, Any]] = None,
    evidence: Optional[Sequence[str]] = None,
    retrieval: Optional[Any] = None,
    analysis_changed_since: bool = False,
) -> Dict[str, Any]:
    """Gate one answer through the full invariant pipeline.

    ``retrieval``, when supplied, lets a caller prove the scope refusals fire
    BEFORE any retrieval happens: the refusal returns first and retrieval is
    never invoked. Every verdict comes from ``_evaluate_invariants`` — there is
    no other path, and no flag skips it.
    """
    return _evaluate_invariants(
        query=query,
        answer=answer,
        live_state=live_state,
        spread_type=spread_type,
        region=region,
        static_or_dynamic=static_or_dynamic,
        failure_case=failure_case,
        live_state_ref=live_state_ref,
        forecast=forecast,
        evidence=list(evidence or []),
        retrieval=retrieval,
        analysis_changed_since=analysis_changed_since,
    )
