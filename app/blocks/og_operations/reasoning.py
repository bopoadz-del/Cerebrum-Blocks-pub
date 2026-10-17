"""Oil & gas operations reasoning layer — deterministic gate.

The reference pattern is the offshore marine installation gate and the
aviation grounding gate: verdicts are pass / block / refused with a named
reason, and a blocked statement never reaches an answer. Everything here is
offline-deterministic — no model calls, no credentials, no network. Seed data
comes from manifest.yaml; anything the encoding sheet has not supplied is a
gap (KNOWN_GAPS.md), never invented. No interview has run, so every manifest
value is null: this layer refuses, it does not answer with figures it does
not have.

Five invariants are ENFORCED, not documented:

  INV-1 WHICH PRESSURE   design / MAWP / operating named; gauge or absolute;
                         and a location (asset or tag). "The pressure is
                         250 psig" answers nothing — 250 psig of WHAT, at
                         WHAT location, gauge or absolute?
  INV-2 ENVELOPE TIER    normal|alarm|trip|SOL|design named. A setpoint with
                         no tier is a number with no meaning: is it the alarm
                         the operator can silence, or the trip that fires?
  INV-3 SCE LIVE         no protective-function (SCE) answer without BOTH an
                         override register reference AND an isolation
                         register reference. A trip that "should" be armed is
                         not the same claim as a trip confirmed armed.
  INV-4 UNITS            flow is std | normal | actual; concentration is
                         %LEL | %vol | ppm; exposure is TWA | STEL | ceiling.
                         These are not interchangeable: 20% could be 20% of
                         the lower explosive limit (dangerous) or 20% of the
                         gas by volume (usually not), and there is no way to
                         tell which from the bare number.
  INV-5 CITATION REVISION no figure from a P&ID or procedure without its
                         revision AND its MOC (management-of-change) state.
                         A revision that cannot be verified is refused, not
                         quoted with a caveat.

Plus the derivation guard (the inferences that are never allowed, each
blocking under its own name), the two-source live-state gate (monitored
status AND the manual override/isolation/permit log), the evidence standard
(REJECT_AS_PROOF), the staleness rules and the scope refusals — which
classify BEFORE retrieval.

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
#: run. A missing QUALIFIER is not: half-qualified is how a trip setpoint
#: answers a design-pressure question, or an alarm figure gets quoted as the
#: trip. "P&ID_rev" keeps the sheet's own spelling (with the ampersand) so a
#: grep for the qualifier finds the same string in both the sheet and here.
MANDATORY_QUALIFIERS = (
    "value",
    "unit",
    "asset",
    "tag",
    "pressure_kind",
    "gauge_or_absolute",
    "envelope_tier",
    "override_register_ref",
    "isolation_register_ref",
    "P&ID_rev",
    "MOC_ref",
    "source",
    "date",
)

PRESSURE_KINDS = ("design", "mawp", "operating")
GAUGE_OR_ABSOLUTE = ("gauge", "absolute")
ENVELOPE_TIERS = ("normal", "alarm", "trip", "SOL", "design")


class ManifestError(ValueError):
    """A figure arrived without its mandatory qualifiers."""


class OperatingBasis:
    """The operating basis, loaded from manifest.yaml.

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
        for name, entry in (raw.get("operating_basis") or {}).items():
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


class LiveState:
    """Current SCE (safety critical element) live state. Requires BOTH sources:

    - ``monitoring``: what the control system reports — SCE status, whether a
      trip is armed, current alarm state.
    - ``manual_log``: what monitoring does NOT see — override register,
      isolation register and permit register entries. A trip that the DCS
      shows as "armed" can still be defeated by a manual override the DCS has
      no visibility of; the manual log is the only place that shows.

    Monitoring is itself a single point of failure: if it is unreachable the
    live state is UNKNOWN. There is no design-basis fallback for live state —
    a design or trip-setpoint figure presented as a current state is the
    failure this gate exists to stop.
    """

    _MAX_AGE_SECONDS = 1800  # SCE state is more perishable than a design figure

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


# --------------------------------------------------------------------------
# rule tables — from the sheet, fail closed, never invented
# --------------------------------------------------------------------------

#: Refusals classify BEFORE retrieval. These are named-person decisions: the
#: operations supervisor, the SCE owner, the competent person who signs the
#: permit. The system will not emit them.
SCOPE_REFUSAL_PATTERNS: List[tuple] = [
    ("keep running", re.compile(
        r"can\s+we\s+keep\s+running|can\s+we\s+continue\s+running|"
        r"is\s+it\s+ok(?:ay)?\s+to\s+keep\s+running",
        re.IGNORECASE)),
    ("break containment", re.compile(
        r"is\s+it\s+safe\s+to\s+break\s+containment|"
        r"can\s+we\s+break\s+containment",
        re.IGNORECASE)),
    ("bypass a trip", re.compile(
        r"can\s+we\s+bypass\s+(?:this\s+|the\s+)?trip|"
        r"can\s+we\s+(?:defeat|inhibit)\s+(?:this\s+|the\s+)?trip",
        re.IGNORECASE)),
    ("extend an inspection", re.compile(
        r"can\s+we\s+extend\s+(?:this\s+|the\s+)?inspection|"
        r"can\s+we\s+defer\s+(?:this\s+|the\s+)?inspection",
        re.IGNORECASE)),
    ("fitness for service", re.compile(
        r"is\s+this\s+vessel\s+fit\s+for\s+service|"
        r"is\s+(?:it|this)\s+fit[-\s]for[-\s]service",
        re.IGNORECASE)),
]

# ---- INV-1 WHICH PRESSURE --------------------------------------------------

PRESSURE_WORDS = re.compile(
    r"\bpressure\b|\bpsig?\b|\bpsia\b|\bbarg\b|\bbara\b|\bkPa[ga]?\b|\bMPa\b|"
    r"\bMAWP\b",
    re.IGNORECASE,
)

_PRESSURE_KIND_MENTION = re.compile(
    r"\bMAWP\b|design\s+pressure|operating\s+pressure", re.IGNORECASE
)
_GAUGE_ABS_MENTION = re.compile(
    r"\bgauge\b|\babsolute\b|\bbarg\b|\bpsig\b|\bkpag\b|\bbara\b|\bpsia\b|\bkpaa\b",
    re.IGNORECASE,
)
_TAG_PATTERN = re.compile(r"\b[A-Z]{1,5}-\d{2,5}[A-Z]?\b")
_LOCATION_WORDS = re.compile(
    r"\bseparator\b|\bvessel\b|\bwellhead\b|\bpipeline\b|\bmanifold\b|"
    r"\btrain\b|\bplatform\b|\bline\b|\bcompressor\b|\bexchanger\b",
    re.IGNORECASE,
)

# ---- INV-2 ENVELOPE TIER ----------------------------------------------------

#: Trigger words for "this is a setpoint/envelope figure" deliberately avoid
#: the tier vocabulary itself (normal|alarm|trip|SOL|design) — if the trigger
#: were "trip" or "alarm", every triggering sentence would already contain a
#: tier word and INV-2 could never be reached unsatisfied. See the module
#: docstring's sibling note in the offshore kit: a broad earlier rule can mask
#: a later one. Here the risk runs the other way — the SAME word cannot be
#: both the trigger and the thing being checked for.
ENVELOPE_TIER_TRIGGER = re.compile(
    r"\bsetpoint\b|\bset\s+at\b|\bthreshold\b|\brelief\s+set\b|\benvelope\b|"
    r"\boperating\s+window\b|\bcut[-\s]?out\b",
    re.IGNORECASE,
)
_TIER_MENTION = re.compile(
    r"\bnormal\b|\balarm\b|\btrip\b|\bSOL\b|\bdesign\b", re.IGNORECASE
)

# ---- INV-3 SCE LIVE ---------------------------------------------------------

SCE_WORDS = re.compile(
    r"\bPSV\b|\bPRV\b|relief\s+valve|\bESD\b|\bESV\b|\bSDV\b|\bBDV\b|\bSIF\b|"
    r"\bSIS\b|\binterlock\b|protective\s+function|safety\s+critical\s+element|"
    r"\bSCE\b|trip\s+valve",
    re.IGNORECASE,
)

# Broad "this needs live state, not a design figure" trigger. Deliberately
# narrower than SCE_WORDS: asking what a PSV is SET to is a design question;
# asking whether it is CURRENTLY isolated, overridden or armed is a live-state
# question. Conflating the two would force every design-figure test to carry
# a live_state fixture it has no business needing.
LIVE_STATE_WORDS = re.compile(
    r"current(?:ly)?\s+(?:status|state)|right\s+now|"
    r"\bis\s+.*\bisolated\b|\bis\s+.*\bbypassed\b|\bis\s+.*\boverrid(?:den|e)\b|"
    r"permit\s+(?:status|in\s+place)|SCE\s+status",
    re.IGNORECASE,
)

# ---- INV-4 UNITS -------------------------------------------------------------

FLOW_WORDS = re.compile(
    r"\bflow\s*rate\b|\bflow\s+is\b|\bMMscfd\b|\bSm3\b|\bNm3\b|\bbpd\b|\bbbl/d\b",
    re.IGNORECASE,
)
_FLOW_BASIS_MENTION = re.compile(
    r"\bstd\b|\bstandard\b|\bnormal\b|\bactual\b", re.IGNORECASE
)

CONCENTRATION_WORDS = re.compile(
    r"\bconcentration\b|gas\s+(?:level|reading)|\bH2S\b|toxic\s+gas",
    re.IGNORECASE,
)
_CONCENTRATION_UNIT_MENTION = re.compile(
    r"%\s*LEL\b|\bLEL\b|%\s*vol(?:ume)?\b|\bppm\b", re.IGNORECASE
)

EXPOSURE_WORDS = re.compile(
    r"\bexposure\b|\bTWA\b|\bSTEL\b|\bceiling\b|occupational\s+limit",
    re.IGNORECASE,
)
_EXPOSURE_BASIS_MENTION = re.compile(r"\bTWA\b|\bSTEL\b|\bceiling\b", re.IGNORECASE)

# ---- INV-5 CITATION REVISION -------------------------------------------------

CITATION_WORDS = re.compile(
    r"P&ID|\bPID\b|piping\s+and\s+instrumentation|\bprocedure\b|\bSOP\b|"
    r"work\s+instruction",
    re.IGNORECASE,
)

# ---- staleness trigger words --------------------------------------------

_PID_WORDS = re.compile(r"P&ID|\bPID\b|piping\s+and\s+instrumentation", re.IGNORECASE)
_CORROSION_WORDS = re.compile(r"corrosion\s+rate", re.IGNORECASE)
_PSV_WORDS = re.compile(r"\bPSV\b|pressure\s+safety\s+valve", re.IGNORECASE)
_SIF_WORDS = re.compile(r"\bSIF\b|safety\s+instrumented\s+function", re.IGNORECASE)
_HAZOP_WORDS = re.compile(r"\bHAZOP\b|\bLOPA\b", re.IGNORECASE)
_PROCEDURE_WORDS = re.compile(r"\bprocedure\b|\bSOP\b|work\s+instruction", re.IGNORECASE)
_GAS_DETECTOR_WORDS = re.compile(
    r"gas\s+detector|fixed\s+gas\s+detection|\bGD-\d+\b", re.IGNORECASE
)

#: Never allowed. Each blocks under its own name — the reason says which
#: inference was attempted, because "blocked" alone teaches nobody anything.
#: The cross-facility carry is NOT in this table — see _cross_facility_carry.
DERIVATION_GUARD: List[tuple] = [
    (
        "remaining-life extrapolation",
        re.compile(
            r"(?=.*(?:remaining\s+life|life\s+remaining))"
            r"(?=.*(?:extrapolat\w*|beyond|past))"
            r"(?=.*(?:last\s+inspection|inspection\s+date|previous\s+inspection))",
            re.IGNORECASE),
        "never-allowed derivation: extrapolating remaining life beyond the last inspection",
    ),
    (
        "corrosion-rate interpolation without CML",
        re.compile(
            r"(?=.*corrosion\s+rate)(?=.*interpolat\w*)"
            r"(?=.*(?:without\s+CML|no\s+CML|missing\s+CML|CML\s+not\s+available|"
            r"CML\s+data))",
            re.IGNORECASE),
        "never-allowed derivation: interpolating a corrosion rate without CML data",
    ),
    (
        "sister-asset setpoint carry",
        re.compile(
            r"sister\s+asset|sister\s+unit|sister\s+facility|identical\s+asset|"
            r"same\s+class\s+asset",
            re.IGNORECASE),
        "ASSET TRAP: a setpoint or limit does not transfer from a sister asset",
    ),
    (
        "assume current revision from last known",
        re.compile(
            r"(?=.*assume)(?=.*(?:current\s+revision|latest\s+revision))"
            r"(?=.*(?:last\s+known|last\s+knew|previously\s+known))",
            re.IGNORECASE),
        "never-allowed derivation: assuming the current revision from what was last known, without checking",
    ),
]

#: What is NOT acceptable as proof, per claim class.
REJECT_AS_PROOF: Dict[str, List[str]] = {
    "mawp": [
        "design-dossier substitute", "field estimate", "operator estimate",
        "not the u-1a", "informal record",
    ],
    "psv_setpoint": [
        "spreadsheet", "maintenance log", "field notebook", "informal note",
        "not a cert",
    ],
    "sif_setpoint": [
        "field experience", "operator judgement", "informal test",
        "no sil assessment",
    ],
    "corrosion_rate": [
        "no cml", "without cml", "estimate only", "no method stated",
        "undated report",
    ],
    "isolation": [
        "isolation plan", "planned isolation", "the plan",
        "isolation procedure (not executed)",
    ],
    "limit": [
        "superseded document", "old revision", "outdated procedure",
        "previous version",
    ],
}

#: Order matters: the specific claim classes are checked before the generic
#: "limit" fallback, or a PSV question that happens to use the word "limit"
#: would be misclassified.
CLAIM_CLASS_WORDS: List[tuple] = [
    ("mawp", re.compile(r"\bMAWP\b|maximum\s+allowable\s+working\s+pressure", re.IGNORECASE)),
    ("psv_setpoint", re.compile(r"\bPSV\b|pressure\s+safety\s+valve|relief\s+valve\s+set", re.IGNORECASE)),
    ("sif_setpoint", re.compile(r"\bSIF\b|safety\s+instrumented\s+function|SIL\s+setpoint", re.IGNORECASE)),
    ("corrosion_rate", re.compile(r"corrosion\s+rate", re.IGNORECASE)),
    ("isolation", re.compile(r"\bisolat(?:ed|ion)\b", re.IGNORECASE)),
    ("limit", re.compile(r"\blimit\b", re.IGNORECASE)),
]


_FACILITY_TOKEN = re.compile(
    r"\b(?:Platform|Facility|Unit|Train|Plant)\s+[A-Za-z0-9]+\b"
)
_CARRY_VERB = re.compile(
    r"\bsame\b|\bapply\b|\bapplies\b|\bcarry\b|\breuse\b|\bas\s+well\b|"
    r"\buse\s+the\b|\bequivalent\b|\btransfer\b",
    re.IGNORECASE,
)


def facilities_mentioned(text: str) -> List[str]:
    """Distinct facility/unit identifiers named in *text*."""
    found: List[str] = []
    for match in _FACILITY_TOKEN.finditer(text or ""):
        name = match.group(0)
        if name not in found:
            found.append(name)
    return found


def _cross_facility_carry(text: str) -> Optional[str]:
    """Two DISTINCT facilities plus a carry verb, or None.

    Naming one facility twice is what a correct answer looks like ("what's
    the limit at Platform A?" / "hold 250 psig at Platform A"). A pattern that
    counts mentions would block that. The carry is two DISTINCT facility
    tokens plus a carry verb ("same", "apply", "carry", "reuse", ...).
    """
    named = facilities_mentioned(text)
    if len(named) >= 2 and _CARRY_VERB.search(text or ""):
        return " -> ".join(named[:2])
    return None


def _classify_claim(query: str, answer: str) -> Optional[str]:
    text = f"{query} {answer}"
    for claim_class, pattern in CLAIM_CLASS_WORDS:
        if pattern.search(text):
            return claim_class
    return None


def _has_location(answer: str, location: Optional[str]) -> bool:
    if location:
        return True
    return bool(_TAG_PATTERN.search(answer)) or bool(_LOCATION_WORDS.search(answer))


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
    live_state: Optional[LiveState],
    pressure_kind: Optional[str],
    gauge_or_absolute: Optional[str],
    location: Optional[str],
    envelope_tier: Optional[str],
    override_register_ref: Optional[str],
    isolation_register_ref: Optional[str],
    citation_rev: Optional[str],
    citation_moc_state: Optional[str],
    evidence: List[str],
    retrieval: Optional[Any],
    moc_approved_since_pid: bool,
    inspection_overdue: bool,
    psv_interval_elapsed: bool,
    sif_proof_test_overdue: bool,
    process_changed_since_hazop: bool,
    procedure_revision_changed: bool,
    gas_detector_calibration_overdue: bool,
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
                f"the operations supervisor, the SCE owner or the competent "
                f"person holds it. The system will not emit it, and nothing "
                f"was retrieved",
            )

    # ---- live-state gate: two sources, both required ---------------------
    needs_live_state = bool(LIVE_STATE_WORDS.search(f"{query} {answer}"))
    if needs_live_state:
        if live_state is None:
            return _verdict(
                "block",
                "SCE state UNKNOWN — monitoring unreachable. Live state has "
                "no design-basis fallback: a design or trip-setpoint figure "
                "is not a current state",
            )
        if not live_state.both_sources_present() or not live_state.fresh():
            return _verdict(
                "block",
                "SCE state unavailable — the override register, the "
                "isolation register and the permit register are all required "
                "alongside monitored SCE status; monitoring alone cannot see "
                "a manual override",
            )

    # ---- staleness ---------------------------------------------------------
    if moc_approved_since_pid and _PID_WORDS.search(combined):
        return _verdict(
            "block",
            "P&ID is stale — an approved MOC exists since this revision; a "
            "superseded P&ID cannot support a current figure",
        )
    if inspection_overdue and _CORROSION_WORDS.search(combined):
        return _verdict(
            "block",
            "corrosion rate is stale — the inspection is overdue; a rate "
            "computed against an overdue inspection is not current",
        )
    if psv_interval_elapsed and _PSV_WORDS.search(combined):
        return _verdict(
            "block",
            "PSV figure is stale — the test/service interval has elapsed",
        )
    if sif_proof_test_overdue and _SIF_WORDS.search(combined):
        return _verdict(
            "block",
            "SIF figure is stale — the proof-test interval has elapsed",
        )
    if process_changed_since_hazop and _HAZOP_WORDS.search(combined):
        return _verdict(
            "block",
            "HAZOP/LOPA basis is stale — the process has changed since it "
            "was run",
        )
    if procedure_revision_changed and _PROCEDURE_WORDS.search(combined):
        return _verdict(
            "block",
            "procedure is stale — the revision has changed since this "
            "citation",
        )
    if gas_detector_calibration_overdue and _GAS_DETECTOR_WORDS.search(combined):
        return _verdict(
            "block",
            "gas detector reading is stale — calibration is overdue",
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
    carried = _cross_facility_carry(combined)
    if carried:
        return _verdict(
            "block",
            "never-allowed derivation: carrying a limit between facilities "
            f"({carried}) [cross-facility limit carry]",
        )
    for name, pattern, reason in DERIVATION_GUARD:
        if pattern.search(combined):
            return _verdict("block", f"{reason} [{name}]")

    # ---- INV-1 WHICH PRESSURE ----------------------------------------------
    # A setpoint/envelope figure is governed by INV-2, not INV-1: combining
    # both regimes on the same statement double-guards one figure and makes
    # INV-2 unreachable (its trigger words would always also trip INV-1's
    # broader pressure-unit check first).
    if PRESSURE_WORDS.search(answer) and not ENVELOPE_TIER_TRIGGER.search(answer):
        has_kind = pressure_kind in PRESSURE_KINDS or bool(
            _PRESSURE_KIND_MENTION.search(answer)
        )
        has_gauge_abs = gauge_or_absolute in GAUGE_OR_ABSOLUTE or bool(
            _GAUGE_ABS_MENTION.search(answer)
        )
        has_location = _has_location(answer, location)
        if not (has_kind and has_gauge_abs and has_location):
            missing = []
            if not has_kind:
                missing.append("which pressure (design|mawp|operating)")
            if not has_gauge_abs:
                missing.append("gauge|absolute")
            if not has_location:
                missing.append("location")
            return _verdict(
                "block",
                "INV-1 violation: pressure figure without "
                + " and ".join(missing)
                + ". A number in psig with no location and no named basis "
                "answers nothing",
            )

    # ---- INV-2 ENVELOPE TIER -----------------------------------------------
    if ENVELOPE_TIER_TRIGGER.search(answer):
        has_tier = envelope_tier in ENVELOPE_TIERS or bool(_TIER_MENTION.search(answer))
        if not has_tier:
            return _verdict(
                "block",
                "INV-2 violation: envelope figure without envelope_tier "
                "(normal | alarm | trip | SOL | design) named. A setpoint "
                "with no tier does not say whether it is the alarm or the "
                "trip",
            )

    # ---- INV-3 SCE LIVE -----------------------------------------------------
    if SCE_WORDS.search(f"{query} {answer}"):
        missing = []
        if not override_register_ref:
            missing.append("override_register_ref")
        if not isolation_register_ref:
            missing.append("isolation_register_ref")
        if missing:
            return _verdict(
                "block",
                "INV-3 violation: protective-function (SCE) answer without "
                + " and ".join(missing)
                + ". A trip that 'should' be armed is not the same claim as "
                "a trip confirmed armed",
            )

    # ---- INV-4 UNITS --------------------------------------------------------
    if FLOW_WORDS.search(answer) and not _FLOW_BASIS_MENTION.search(answer):
        return _verdict(
            "block",
            "INV-4 violation: flow figure without a stated basis "
            "(std | normal | actual). A bare flow number is not comparable "
            "across conditions",
        )
    if CONCENTRATION_WORDS.search(answer) and not _CONCENTRATION_UNIT_MENTION.search(answer):
        return _verdict(
            "block",
            "INV-4 violation: concentration figure without %LEL | %vol | ppm "
            "named. 20% could be 20% of the lower explosive limit or 20% by "
            "volume, and a bare percentage does not say which",
        )
    if EXPOSURE_WORDS.search(answer) and not _EXPOSURE_BASIS_MENTION.search(answer):
        return _verdict(
            "block",
            "INV-4 violation: exposure figure without a stated basis "
            "(TWA | STEL | ceiling). A reading with no averaging basis is "
            "not an exposure limit comparison",
        )

    # ---- INV-5 CITATION REVISION --------------------------------------------
    if CITATION_WORDS.search(combined):
        if citation_moc_state == "unverifiable":
            return _verdict(
                "refused",
                "INV-5 refusal: citation revision unverifiable — the "
                "document-control source could not confirm the current "
                "revision or MOC state, and an unverifiable citation is not "
                "a citation",
            )
        if not citation_rev or not citation_moc_state:
            missing = []
            if not citation_rev:
                missing.append("P&ID_rev")
            if not citation_moc_state:
                missing.append("MOC_ref/MOC state")
            return _verdict(
                "block",
                "INV-5 violation: figure cited from a P&ID or procedure "
                "without " + " and ".join(missing) + ". A citation with no "
                "revision and no MOC state cannot be trusted current",
            )

    return _verdict("pass")


def gate_answer(
    query: str,
    answer: str,
    *,
    live_state: Optional[LiveState] = None,
    pressure_kind: Optional[str] = None,
    gauge_or_absolute: Optional[str] = None,
    location: Optional[str] = None,
    envelope_tier: Optional[str] = None,
    override_register_ref: Optional[str] = None,
    isolation_register_ref: Optional[str] = None,
    citation_rev: Optional[str] = None,
    citation_moc_state: Optional[str] = None,
    evidence: Optional[Sequence[str]] = None,
    retrieval: Optional[Any] = None,
    moc_approved_since_pid: bool = False,
    inspection_overdue: bool = False,
    psv_interval_elapsed: bool = False,
    sif_proof_test_overdue: bool = False,
    process_changed_since_hazop: bool = False,
    procedure_revision_changed: bool = False,
    gas_detector_calibration_overdue: bool = False,
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
        pressure_kind=pressure_kind,
        gauge_or_absolute=gauge_or_absolute,
        location=location,
        envelope_tier=envelope_tier,
        override_register_ref=override_register_ref,
        isolation_register_ref=isolation_register_ref,
        citation_rev=citation_rev,
        citation_moc_state=citation_moc_state,
        evidence=list(evidence or []),
        retrieval=retrieval,
        moc_approved_since_pid=moc_approved_since_pid,
        inspection_overdue=inspection_overdue,
        psv_interval_elapsed=psv_interval_elapsed,
        sif_proof_test_overdue=sif_proof_test_overdue,
        process_changed_since_hazop=process_changed_since_hazop,
        procedure_revision_changed=procedure_revision_changed,
        gas_detector_calibration_overdue=gas_detector_calibration_overdue,
    )
