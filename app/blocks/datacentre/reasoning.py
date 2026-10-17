"""Data centre reasoning layer — deterministic gate for facility_01 statements.

The reference pattern is the aviation grounding gate: verdicts are
pass / block / refused with a named reason; blocked statements never
reach an answer. Everything here is offline-deterministic — no model
calls, no credentials, no network. Seed data comes from manifest.yaml;
anything the encoding sheet did not supply is a gap (KNOWN_GAPS.md),
never invented.

Four invariants are ENFORCED, not documented:
  INV-1 "tested" claims must carry commissioning_level + load_pct +
        failure_scenario.
  INV-2 resilience claims must carry a basis
        (as_designed | as_built | as_currently_operating).
  INV-3 capacity figures must state whether redundancy is reserved
        (design | installed | available_after_redundancy).
  INV-4 the facility may never be declared ready for IT load, or a
        current resilience level invented — refusal happens BEFORE
        retrieval.

Plus the derivation guard (never-allowed inferences), the two-source
live-state gate (BMS + manual log), the evidence standard
(REJECT_AS_PROOF + tier trap), staleness rules and the closing-window
rule. Any single violation blocks the WHOLE answer.
"""
from __future__ import annotations

import pathlib
import re
import time
from typing import Any, Dict, List, Optional

import yaml

# --------------------------------------------------------------------------
# provenance / manifest
# --------------------------------------------------------------------------

_MANIFEST_PATH = pathlib.Path(__file__).parent / "design_basis.yaml"


class DesignBasis:
    """facility_01 design basis, loaded from manifest.yaml.

    Every value keeps its provenance: value, unit, source (domain
    encoding sheet, facility_01), scope (facility-specific — never
    carry to another site).
    """

    def __init__(self, manifest_path: Optional[pathlib.Path] = None) -> None:
        path = manifest_path or _MANIFEST_PATH
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.facility = raw["facility"]
        self.source = raw["source"]
        self.scope = raw["scope"]
        self._entries: Dict[str, Dict[str, Any]] = {}
        for name, entry in raw["design_basis"].items():
            self._entries[name] = {
                "value": entry["value"],
                "unit": entry["unit"],
                "source": self.source,
                "scope": self.scope,
            }

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        entries = self.__dict__.get("_entries")
        if entries is not None and name in entries:
            return entries[name]["value"]
        raise AttributeError(name)

    def field(self, name: str) -> Dict[str, Any]:
        """Provenance record for one design-basis value."""
        return dict(self._entries[name])

    def fields(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._entries)


# --------------------------------------------------------------------------
# live state — two sources, both required
# --------------------------------------------------------------------------

class ResilienceState:
    """Current resilience state. Requires BOTH sources:

    - bms: what the BMS monitors (chillers, pumps, CRAC/CRAH, UPS,
      generator status).
    - manual_log: what the BMS does NOT monitor — manual isolations,
      racked-out breakers, manual bypasses, components out.

    The BMS control panel is itself a single point of failure: if BMS
    is unreachable, facility state is UNKNOWN — never design basis.
    """

    _MAX_AGE_SECONDS = 3600

    def __init__(
        self,
        bms: Optional[Dict[str, Any]],
        manual_log: Optional[Dict[str, Any]],
        fetched_at: Optional[float] = None,
    ) -> None:
        self.bms = bms
        self.manual_log = manual_log
        self.fetched_at = fetched_at if fetched_at is not None else time.time()

    def both_sources_present(self) -> bool:
        return self.bms is not None and self.manual_log is not None

    def fresh(self) -> bool:
        return (time.time() - self.fetched_at) <= self._MAX_AGE_SECONDS

    def components_out(self) -> List[Dict[str, Any]]:
        log = self.manual_log or {}
        return list(log.get("components_out") or [])


# --------------------------------------------------------------------------
# rule tables (from the sheet — fail closed, never invented)
# --------------------------------------------------------------------------

BASIS_LABELS = ("as_designed", "as_built", "as_currently_operating")

RESILIENCE_WORDS = re.compile(
    r"n\+\d|n[-\s]?\d|redundan\w*|resilien\w*|fault[-\s]?toleran\w*|"
    r"concurrent\s+maintainab\w*|single\s+point\s+of\s+failure",
    re.IGNORECASE,
)

LIVE_STATE_WORDS = re.compile(
    r"ride[-\s]?through|thermal|redundan\w*|resilien\w*|protection|"
    r"n\+\d|current\s+resilien\w*|single\s+point",
    re.IGNORECASE,
)

TESTED_MARKERS = re.compile(
    r"\btested\b|test\s+result|\bpassed\b.*\btest\b|\bIST\b",
    re.IGNORECASE,
)

LEVEL_PATTERN = re.compile(r"\bL[1-5]\b|level\s+L?[1-5]", re.IGNORECASE)
LOAD_PCT_PATTERN = re.compile(r"\d+(?:\.\d+)?\s*%")
SCENARIO_PATTERN = re.compile(
    r"failure|loss|fault|outage|trip|bypass|isolation|ride[-\s]?through|"
    r"thermal|chiller|power",
    re.IGNORECASE,
)

CAPACITY_PATTERN = re.compile(
    r"available\s+capacity|capacity\s+(?:is|of)\s+|remaining\s+capacity|"
    r"spare\s+capacity|capacity\s+available|"
    r"\d+(?:\.\d+)?\s*(?:MW|kW|kVA)\s*(?:available|remaining)",
    re.IGNORECASE,
)
CAPACITY_BASIS_PATTERN = re.compile(
    r"design|installed|available_after_redundancy|available\s+after\s+redundancy|"
    r"after\s+redundancy",
    re.IGNORECASE,
)

SCOPE_REFUSAL_PATTERN = re.compile(
    r"ready\s+for\s+IT\s+load|ready\s+for\s+live\s+load|safe\s+to\s+energise|"
    r"safe\s+to\s+energize|authorise\s+go[-\s]?live|accept\s+IT\s+load|"
    r"clear\s+for\s+go[-\s]?live",
    re.IGNORECASE,
)

NEVER_ALLOWED_PATTERNS: List[tuple] = [
    # name, compiled pattern, reason fragment
    (
        "partial-to-full extrapolation",
        re.compile(
            r"(?=.*(?:partial|day[-\s]?one|25\s*%|low\s+load))"
            r"(?=.*(?:full\s+load|design\s+load|extrapolat))",
            re.IGNORECASE,
        ),
        "never-allowed derivation: extrapolating results from partial load to full load",
    ),
    (
        "design-basis-to-current-resilience",
        re.compile(
            r"design\s+basis.*(current|today|now|operat)",
            re.IGNORECASE,
        ),
        "never-allowed derivation: inferring current resilience from the design basis",
    ),
    (
        "resilience-from-single-line",
        re.compile(
            r"single[\s-]line\s+diagram.*(redundan|resilien|N\+\d)",
            re.IGNORECASE,
        ),
        "never-allowed derivation: inferring resilience from the single line diagram",
    ),
    (
        "performance-from-individual-test",
        re.compile(
            r"(performance|capacity|capab\w+).*(functional\s+test|L[1-5]\s+test)",
            re.IGNORECASE,
        ),
        "never-allowed derivation: inferring facility performance from individual system tests",
    ),
    (
        "ride-through-from-calculation",
        re.compile(
            r"ride[-\s]?through.*(calculat|simulat|model)",
            re.IGNORECASE,
        ),
        "never-allowed derivation: inferring thermal ride-through from calculation alone",
    ),
]

# What is NOT acceptable as proof, per claim class (from the sheet).
REJECT_AS_PROOF: Dict[str, List[str]] = {
    "resilience_claim": ["single line diagram", "tier design certificate"],
    "system_capability": ["passed l4 functional test"],
    "available_capacity": ["design capacity"],
    "ride_through": ["manufacturer specification", "calculation"],
    "current_resilience": ["design basis"],
    "concurrent_maintainability": ["desktop review"],
    "fire_system_status": ["installation certificate"],
}

CLAIM_CLASS_WORDS: List[tuple] = [
    ("ride_through", re.compile(r"ride[-\s]?through|thermal", re.IGNORECASE)),
    ("resilience_claim", re.compile(r"redundan|resilien|N\+\d|single line", re.IGNORECASE)),
    ("available_capacity", re.compile(r"available capacity|capacity available", re.IGNORECASE)),
    ("current_resilience", re.compile(r"current resilience|right now|today", re.IGNORECASE)),
    ("concurrent_maintainability", re.compile(r"concurrent maintainab", re.IGNORECASE)),
    ("fire_system_status", re.compile(r"fire", re.IGNORECASE)),
    ("system_capability", re.compile(r"functional test|L[1-5]|capab", re.IGNORECASE)),
]

TIER_DESIGN_PATTERN = re.compile(r"tier\s+design\s+certificat", re.IGNORECASE)
TIER_CONSTRUCTED_PATTERN = re.compile(r"construct", re.IGNORECASE)

IST_PATTERN = re.compile(r"\bIST\b", re.IGNORECASE)


def _classify_claim(query: str, answer: str) -> Optional[str]:
    text = f"{query} {answer}"
    for claim_class, pattern in CLAIM_CLASS_WORDS:
        if pattern.search(text):
            return claim_class
    return None


# --------------------------------------------------------------------------
# verdict construction — one factory, no bypasses
# --------------------------------------------------------------------------

def _verdict(verdict: str, reason: str = "", corrected: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    result: Dict[str, Any] = {"verdict": verdict}
    if verdict in ("block", "refused"):
        result["blocked_reason"] = reason
    if corrected is not None:
        result["corrected"] = corrected
    return result


# --------------------------------------------------------------------------
# the invariant pipeline
# --------------------------------------------------------------------------

def _evaluate_invariants(
    query: str,
    answer: str,
    live_state: Optional[ResilienceState],
    basis: Optional[str],
    evidence: List[str],
    retrieval: Optional[Any],
    test_modified_since_ist: bool,
) -> Dict[str, Any]:
    # INV-4 — classify BEFORE retrieval. Readiness declarations are
    # named-person decisions; refuse without retrieving anything.
    if SCOPE_REFUSAL_PATTERN.search(query):
        return _verdict(
            "refused",
            "INV-4 scope refusal: declaring the facility ready for IT load is "
            "a named-person decision; the system will not emit it",
        )

    # Live-state gate: any redundancy / ride-through / protection
    # question must read current live state first.
    needs_live_state = bool(LIVE_STATE_WORDS.search(f"{query} {answer}"))
    degraded: List[Dict[str, Any]] = []
    if needs_live_state:
        if live_state is None:
            return _verdict(
                "block",
                "current resilience state unavailable — facility state unknown "
                "(BMS unreachable). Live state has no design-basis fallback",
            )
        if not live_state.both_sources_present() or not live_state.fresh():
            return _verdict(
                "block",
                "current resilience state unavailable — BMS reading and manual "
                "log both required",
            )
        degraded = live_state.components_out()

    # Closing-window / staleness: an IST result is stale once the tested
    # systems were modified.
    if test_modified_since_ist and IST_PATTERN.search(f"{query} {answer} {' '.join(evidence)}"):
        return _verdict(
            "block",
            "IST result is stale — the tested systems have been modified since "
            "the test; it cannot support a current claim",
        )
    if re.search(r"full[-\s]?facility", answer, re.IGNORECASE) and TESTED_MARKERS.search(answer):
        return _verdict(
            "block",
            "unproven — test window closed: full-facility failure testing cannot "
            "be repeated once IT load is live",
        )

    # Evidence standard: REJECT_AS_PROOF + the tier trap.
    claim_class = _classify_claim(query, answer)
    for citation in evidence:
        lower_citation = citation.lower()
        evidence_class = None
        for cls, rejected in REJECT_AS_PROOF.items():
            if any(fragment in lower_citation for fragment in rejected):
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
        if TIER_DESIGN_PATTERN.search(citation) and TIER_CONSTRUCTED_PATTERN.search(query + answer):
            return _verdict(
                "block",
                "tier trap: a Tier design certification is not evidence of a "
                "Tier constructed facility certification",
            )

    # Derivation guard — never-allowed inferences.
    combined = f"{query} {answer} {' '.join(evidence)}"
    for name, pattern, reason in NEVER_ALLOWED_PATTERNS:
        if pattern.search(combined):
            return _verdict("block", reason)

    # INV-1 — any "tested" output must carry level + load + scenario.
    if TESTED_MARKERS.search(answer):
        has_level = bool(LEVEL_PATTERN.search(answer))
        has_load = bool(LOAD_PCT_PATTERN.search(answer))
        has_scenario = bool(SCENARIO_PATTERN.search(answer))
        if not (has_level and has_load and has_scenario):
            return _verdict(
                "block",
                "INV-1 violation: test claim without level and load — 'tested' "
                "outputs must carry commissioning_level (L1-L5), load_pct and "
                "failure_scenario",
            )

    # INV-2 — resilience statements must carry a basis.
    if RESILIENCE_WORDS.search(answer):
        basis_given = basis in BASIS_LABELS or any(
            label in answer.lower() for label in BASIS_LABELS
        )
        if not basis_given:
            return _verdict(
                "block",
                "INV-2 violation: resilience claim without basis "
                "(as_designed | as_built | as_currently_operating)",
            )

    # INV-3 — capacity figures must state whether redundancy is reserved.
    if CAPACITY_PATTERN.search(answer) and not CAPACITY_BASIS_PATTERN.search(answer):
        return _verdict(
            "block",
            "INV-3 violation: capacity claim without redundancy basis "
            "(design | installed | available_after_redundancy)",
        )

    # N+1 with one component out is N — surface the transition, never
    # infer it silently. Only an as_currently_operating claim is
    # corrected against live state.
    if degraded:
        effective_basis = basis or (
            "as_currently_operating"
            if "as_currently_operating" in answer.lower()
            else None
        )
        if effective_basis == "as_currently_operating":
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
    live_state: Optional[ResilienceState] = None,
    basis: Optional[str] = None,
    evidence: Optional[List[str]] = None,
    retrieval: Optional[Any] = None,
    test_modified_since_ist: bool = False,
) -> Dict[str, Any]:
    """Gate one answer through the full invariant pipeline.

    `retrieval`, when supplied, lets callers prove INV-4 refuses BEFORE
    any retrieval happens (the scope refusal fires first, retrieval is
    never invoked). Every verdict comes from _evaluate_invariants —
    there is no other path, and no flag skips it.
    """
    return _evaluate_invariants(
        query=query,
        answer=answer,
        live_state=live_state,
        basis=basis,
        evidence=list(evidence or []),
        retrieval=retrieval,
        test_modified_since_ist=test_modified_since_ist,
    )
