"""Water treatment plant operations reasoning layer — deterministic gate.

The reference pattern is the offshore marine installation gate and the
aviation grounding gate: verdicts are pass / block / refused with a named
reason, and a blocked statement never reaches an answer. Everything here is
offline-deterministic — no model calls, no credentials, no network. Seed data
comes from manifest.yaml; anything the encoding sheet has not supplied is a
gap (KNOWN_GAPS.md), never invented. No interview has run, so every manifest
value is null: this layer refuses, it does not answer with figures it does
not have.

Five invariants are ENFORCED, not documented:

  INV-1 CT QUALIFIERS      a CT value (required or achieved) is never
                           returned without temperature, pH, disinfectant,
                           organism AND log target. Those five identify which
                           row of the CT table the number came from.
  INV-2 CONTACT-TIME BASIS a contact time is never returned without its basis
                           (theoretical | T10 | tracer), the flow it applies
                           at, and the tank level assumed.
  INV-3 DOSE BASIS         a chemical dose is never returned without its
                           basis (as_product | as_active) and the delivered,
                           measured strength — nameplate strength is not
                           proof.
  INV-4 LIMIT QUALIFIER    a regulatory limit is never returned without its
                           averaging basis, monitoring frequency and the
                           named regulation.
  INV-5 CONFLICT REFUSE    two sources disagreeing on a limit is refused and
                           BOTH sources are reported. This invariant does not
                           pick a winner — a permit stricter than the
                           underlying code is a standing conflict, not
                           something the gate resolves for the caller.

Plus the derivation guard (the inferences that are never allowed, each
blocking under its own name), the two-source live-state gate (SCADA/analyser
AND the chemical delivery log), the evidence standard (REJECT_AS_PROOF), the
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
#: run. A missing QUALIFIER is not: half-qualified is how a CT value read off
#: the wrong temperature/pH row ends up answering the wrong question.
MANDATORY_QUALIFIERS = (
    "value",
    "unit",
    "plant",
    "train",
    "parameter",
    "averaging_basis",
    "regulation",
    "contact_time_basis",
    "CT_T_pH",
    "dose_basis",
    "source",
    "revision",
    "date",
)

CONTACT_TIME_BASIS = ("theoretical", "T10", "tracer")
DOSE_BASIS = ("as_product", "as_active")


class ManifestError(ValueError):
    """A figure arrived without its mandatory qualifiers."""


class TreatmentBasis:
    """The plant treatment/design basis, loaded from manifest.yaml.

    The loader is the first gate. It refuses at LOAD time — not at answer
    time — so a half-qualified figure cannot sit in the manifest waiting to
    be quoted. The refusal names the figure and every key it lacks.
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


class PlantState:
    """Current plant state. Requires BOTH sources:

    - ``scada``: analyser status and SCADA readings vs design — the online,
      continuous telemetry (residual analysers, turbidimeters, flow meters,
      calibration due dates).
    - ``delivery_log``: what SCADA does NOT see — the latest DELIVERED
      chemical strength, from the certificate of analysis for each delivery.
      The nameplate/rated strength on the drum is not the delivered strength.

    SCADA is itself a single point of failure: if it is unreachable the plant
    state is UNKNOWN. There is no design-basis fallback for live state — a
    design figure presented as a current reading is the failure this gate
    exists to stop.
    """

    _MAX_AGE_SECONDS = 3600

    def __init__(
        self,
        scada: Optional[Dict[str, Any]],
        delivery_log: Optional[Dict[str, Any]],
        fetched_at: Optional[float] = None,
    ) -> None:
        self.scada = scada
        self.delivery_log = delivery_log
        self.fetched_at = fetched_at if fetched_at is not None else time.time()

    def both_sources_present(self) -> bool:
        return self.scada is not None and self.delivery_log is not None

    def fresh(self) -> bool:
        return (time.time() - self.fetched_at) <= self._MAX_AGE_SECONDS

    def analyser_calibration_due_at(self) -> Optional[float]:
        return (self.scada or {}).get("calibration_due_at")

    def scada_vs_design_delta(self) -> Optional[Any]:
        return (self.scada or {}).get("scada_vs_design_delta")

    def delivered_strength_pct(self) -> Optional[float]:
        return (self.delivery_log or {}).get("delivered_strength_pct")

    def delivered_at(self) -> Optional[float]:
        return (self.delivery_log or {}).get("delivered_at")


# --------------------------------------------------------------------------
# rule tables — from the sheet, fail closed, never invented
# --------------------------------------------------------------------------

#: Refusals classify BEFORE retrieval. These are named-person decisions: the
#: shift operator, the ORP (operator of record), the safety officer. The
#: system will not emit them.
SCOPE_REFUSAL_PATTERNS: List[tuple] = [
    ("water safety to supply", re.compile(
        r"is\s+(?:this|the)\s+water\s+safe\s+to\s+(?:supply|drink)|"
        r"safe\s+to\s+supply\s+(?:the\s+)?water|can\s+we\s+supply\s+this\s+water",
        re.IGNORECASE)),
    ("skip filter-to-waste", re.compile(
        r"can\s+we\s+skip\s+(?:the\s+)?filter[-\s]?to[-\s]?waste|"
        r"skip\s+filter[-\s]?to[-\s]?waste",
        re.IGNORECASE)),
    ("boil notice", re.compile(
        r"do\s+we\s+need\s+a\s+boil\s+(?:water\s+)?notice|"
        r"boil\s+notice\s+required|issue\s+a\s+boil\s+notice",
        re.IGNORECASE)),
    ("chlorine room entry", re.compile(
        r"can\s+i\s+enter\s+the\s+chlorine\s+room|"
        r"safe\s+to\s+enter\s+the\s+chlorine\s+room|"
        r"enter\s+the\s+chlorine\s+room",
        re.IGNORECASE)),
]

#: A CT value is a disinfection credit, not raw contact time. "CT" alone is
#: too ambiguous (it is a word in plenty of unrelated text), so the pattern
#: requires it be paired with a word that only makes sense in this context.
CT_VALUE_WORDS = re.compile(
    r"\bCT\b\s*(?:required|achieved|value|ratio|credit)|"
    r"\bCT\s+(?:of|is|=)|log\s+(?:inactivation|removal)\s+credit",
    re.IGNORECASE,
)

CONTACT_TIME_WORDS = re.compile(
    r"contact\s+time|detention\s+time|hydraulic\s+retention\s+time|"
    r"residence\s+time|\bT10\b",
    re.IGNORECASE,
)

DOSE_WORDS = re.compile(
    r"\bdose\b|dosing|dosage|feed\s+rate",
    re.IGNORECASE,
)

LIMIT_WORDS = re.compile(
    r"\blimit\b|\bMCL\b|maximum\s+contaminant\s+level|permit\s+limit|"
    r"effluent\s+limit|compliance\s+limit",
    re.IGNORECASE,
)

COMPLIANCE_WORDS = re.compile(
    r"complian\w*|meets?\s+the\s+(?:permit\s+)?limit|in\s+compliance",
    re.IGNORECASE,
)

LIVE_STATE_WORDS = re.compile(
    r"current\s+(?:compliance|status|residual|turbidity|reading)|"
    r"right\s+now|live\s+analyser|analyser\s+reading|real[-\s]?time|"
    r"\bin\s+compliance\s+right\s+now\b",
    re.IGNORECASE,
)

# ---- INV-1 qualifier mentions --------------------------------------------
_TEMP_MENTION = re.compile(
    r"\d+(?:\.\d+)?\s*(?:degC|deg\.?\s*C|\xb0\s?C|celsius)|\btemperature\b",
    re.IGNORECASE,
)
_PH_MENTION = re.compile(r"\bpH\s*\d|\bpH\b", re.IGNORECASE)
_DISINFECTANT_MENTION = re.compile(
    r"free\s+chlorine|chloramine|chlorine\s+dioxide|\bozone\b|\bUV\b|hypochlorite",
    re.IGNORECASE,
)
_ORGANISM_MENTION = re.compile(
    r"giardia|cryptosporidium|\bvirus(?:es)?\b|\bE\.?\s*coli\b|coliform",
    re.IGNORECASE,
)
_LOG_TARGET_MENTION = re.compile(
    r"\d(?:\.\d+)?\s*-?\s*log\b|log\s+(?:removal|inactivation|credit)\s+target",
    re.IGNORECASE,
)

# ---- INV-2 qualifier mentions ---------------------------------------------
_FLOW_MENTION = re.compile(
    r"\d+(?:\.\d+)?\s*(?:mgd|gpm|m3/h|m\xb3/h|l/s|mld)|at\s+(?:a\s+)?flow\s+of|"
    r"peak\s+hour\s+flow|average\s+day\s+flow",
    re.IGNORECASE,
)
_TANK_LEVEL_MENTION = re.compile(
    r"tank\s+level|clearwell\s+level|water\s+level\s+(?:assumed|at)|"
    r"full\s+tank|low\s+water\s+level",
    re.IGNORECASE,
)
_T10_REQUIRED_MENTION = re.compile(
    r"T10\s+(?:tracer\s+study\s+)?(?:is\s+)?required|requires?\s+a\s+T10",
    re.IGNORECASE,
)

# ---- INV-3 qualifier mentions ---------------------------------------------
_DOSE_BASIS_MENTION = re.compile(r"as[-\s]?product|as[-\s]?active", re.IGNORECASE)
_DELIVERED_STRENGTH_MENTION = re.compile(
    r"delivered\s+strength|measured\s+strength|assay(?:ed)?\s+(?:at|strength)|"
    r"available\s+chlorine\s+of\s+\d|trade\s+percent",
    re.IGNORECASE,
)

# ---- INV-4 qualifier mentions ----------------------------------------------
_AVERAGING_MENTION = re.compile(
    r"running\s+annual\s+average|monthly\s+average|daily\s+average|"
    r"instantaneous|\bRAA\b|averaging\s+(?:basis|period)",
    re.IGNORECASE,
)
_FREQUENCY_MENTION = re.compile(
    r"continuous(?:ly)?\s+monitor\w*|grab\s+sample|hourly|daily|weekly|monthly|"
    r"monitoring\s+frequency",
    re.IGNORECASE,
)
_REGULATION_MENTION = re.compile(
    r"\bSDWA\b|safe\s+drinking\s+water\s+act|\bNPDES\b|\bLT2\b|\bSWTR\b|"
    r"\bRTCR\b|state\s+(?:drinking\s+water\s+)?code|permit\s+no|\bEPA\b",
    re.IGNORECASE,
)

#: Never allowed. Each blocks under its own name — the reason says which
#: inference was attempted, because "blocked" alone teaches nobody anything.
DERIVATION_GUARD: List[tuple] = [
    (
        "CT table interpolation",
        re.compile(
            r"(?=.*interpolat\w*)"
            r"(?=.*(?:CT\s+table|temperature\s+rows?|between\s+(?:the\s+)?rows?))",
            re.IGNORECASE),
        "never-allowed derivation: interpolating a CT table between temperature rows",
    ),
    (
        "nameplate hypochlorite strength",
        re.compile(
            r"nameplate\s+(?:strength|concentration)|"
            r"rated\s+(?:strength|concentration)\s+(?:of\s+)?(?:the\s+)?hypochlorite|"
            r"label\s+strength",
            re.IGNORECASE),
        "never-allowed derivation: using nameplate hypochlorite strength instead of "
        "the delivered, measured strength",
    ),
    (
        "design-document compliance",
        re.compile(
            r"(?=.*design\s+(?:document|report|basis|manual))"
            r"(?=.*(?:complian\w*|in\s+compliance|meets?\s+the\s+limit))",
            re.IGNORECASE),
        "never-allowed derivation: assuming a compliance value from a design "
        "document instead of the live analyser",
    ),
]

#: What is NOT acceptable as proof, per claim class.
REJECT_AS_PROOF: Dict[str, List[str]] = {
    "compliance": ["design document", "design report", "as-built compliance"],
    "limit": ["design document", "design report", "expired permit", "old permit", "draft permit"],
    "ct_required": ["average temperature", "wrong temperature row", "assumed ph", "nearest row"],
    "contact_time": ["theoretical detention", "design detention time"],
    "dose": ["nameplate strength", "rated strength", "label strength"],
}

#: Compliance is checked ahead of the more generic "limit" class: a
#: compliance claim usually mentions a limit too, and compliance is the
#: tighter claim (what REJECT_AS_PROOF cares about is the live analyser, not
#: the limit's own qualifiers).
CLAIM_CLASS_WORDS: List[tuple] = [
    ("compliance", COMPLIANCE_WORDS),
    ("limit", LIMIT_WORDS),
    ("ct_required", CT_VALUE_WORDS),
    ("contact_time", CONTACT_TIME_WORDS),
    ("dose", DOSE_WORDS),
]

_PLANT_TOKEN = re.compile(r"\bplant\s+([A-Za-z0-9]+)\b", re.IGNORECASE)
#: Words that follow "plant" as a verb ("plant a garden") rather than as a
#: noun naming a specific facility ("Plant A", "Plant 2"). Single-letter
#: plant identifiers (A, B, ...) are common in this domain, so "a"/"an" are
#: deliberately NOT in this list — filtering them out would make "Plant A"
#: invisible to the carry check.
_PLANT_STOPWORDS = {
    "is", "was", "has", "the", "design", "operations", "water",
    "operator", "staff", "level", "this", "that", "record", "records",
    "manual", "effluent", "influent", "manager", "supervisor",
}
_CARRY_VERB = re.compile(
    r"\bsame\b|\bapply\b|\bapplies\b|\bcarry\b|\breuse\b|\bas\s+well\b|"
    r"\buse\s+the\b|\bequivalent\b|\btransfer\b",
    re.IGNORECASE,
)


def plants_mentioned(text: str) -> List[str]:
    """Distinct plant identifiers named in *text* ("Plant A" -> "a")."""
    found: List[str] = []
    for match in _PLANT_TOKEN.finditer(text or ""):
        name = (match.group(1) or "").lower()
        if not name or name in _PLANT_STOPWORDS:
            continue
        if name not in found:
            found.append(name)
    return found


def _similar_plant_carry(text: str) -> Optional[str]:
    """Two DISTINCT plants plus a carry verb, or None.

    Naming the SAME plant twice is what a correct answer looks like ("the
    dose at Plant A is 2.5 mg/L; Plant A's CT is fine"). A regex that counts
    mentions of "plant" blocks that correct answer. The carry is two
    DISTINCT plant identifiers plus a carry verb (same/apply/carry/reuse).
    """
    named = plants_mentioned(text)
    if len(named) >= 2 and _CARRY_VERB.search(text or ""):
        return " -> ".join(named[:2])
    return None


def _classify_claim(query: str, answer: str) -> Optional[str]:
    text = f"{query} {answer}"
    for claim_class, pattern in CLAIM_CLASS_WORDS:
        if pattern.search(text):
            return claim_class
    return None


def _basis_from_text(text: str) -> Optional[str]:
    if re.search(r"\btracer\b", text, re.IGNORECASE):
        return "tracer"
    if re.search(r"\bT10\b", text, re.IGNORECASE):
        return "T10"
    if re.search(r"\btheoretical\b", text, re.IGNORECASE):
        return "theoretical"
    return None


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


def _conflict(limit_sources: Optional[Sequence[Dict[str, Any]]]) -> Optional[List[tuple]]:
    """Two-or-more sources naming different values for the same limit.

    INV-5 does not pick a winner — a permit stricter than the underlying code
    is a standing conflict, reported, not resolved by this gate.
    """
    if not limit_sources or len(limit_sources) < 2:
        return None
    by_value: Dict[Any, List[str]] = {}
    for entry in limit_sources:
        src = entry.get("source")
        val = entry.get("value")
        if src is None or val is None:
            continue
        by_value.setdefault(val, []).append(src)
    if len(by_value) >= 2:
        return list(by_value.items())
    return None


# --------------------------------------------------------------------------
# the invariant pipeline — one path, no bypass
# --------------------------------------------------------------------------

def _evaluate_invariants(
    query: str,
    answer: str,
    live_state: Optional[PlantState],
    ct_temperature_c: Optional[float],
    ct_ph: Optional[float],
    disinfectant: Optional[str],
    organism: Optional[str],
    log_target: Optional[float],
    contact_time_basis: Optional[str],
    flow: Optional[float],
    tank_level_assumed: Optional[Any],
    t10_required: bool,
    dose_basis: Optional[str],
    delivered_strength: Optional[float],
    strength_recorded_at: Optional[float],
    averaging_basis: Optional[str],
    monitoring_frequency: Optional[str],
    regulation: Optional[str],
    limit_sources: Optional[Sequence[Dict[str, Any]]],
    evidence: List[str],
    retrieval: Optional[Any],
    tracer_or_basis_changed_since: bool,
    permit_changed_since: bool,
    manual_revised_since: bool,
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
                f"the operator of record or safety officer holds it. The "
                f"system will not emit it, and nothing was retrieved",
            )

    # ---- live-state gate: two sources, both required ----------------------
    needs_live_state = bool(LIVE_STATE_WORDS.search(f"{query} {answer}"))
    if needs_live_state:
        if live_state is None:
            return _verdict(
                "block",
                "plant state UNKNOWN — SCADA/analyser unreachable. Live state "
                "has no design-basis fallback: a design figure is not a "
                "current reading",
            )
        if not live_state.both_sources_present() or not live_state.fresh():
            return _verdict(
                "block",
                "plant state unavailable — SCADA/analyser AND the chemical "
                "delivery log are both required; the delivery log carries "
                "what SCADA cannot see (the latest DELIVERED chemical "
                "strength)",
            )

    # ---- staleness ---------------------------------------------------------
    if tracer_or_basis_changed_since and CONTACT_TIME_WORDS.search(combined):
        return _verdict(
            "block",
            "contact-time basis is stale — a physical, operational or "
            "disinfection change has occurred since the tracer/T10 study was "
            "run; it cannot support a current figure",
        )
    if permit_changed_since and LIMIT_WORDS.search(combined):
        return _verdict(
            "block",
            "limit is stale — the permit has been renewed or varied since "
            "this figure was recorded",
        )
    if manual_revised_since and re.search(
        r"operating\s+manual|per\s+the\s+manual|manual\s+says", combined, re.IGNORECASE,
    ):
        return _verdict(
            "block",
            "operating manual reference is stale — the manual has been "
            "revised since this figure was recorded",
        )
    if live_state is not None:
        calib_due = live_state.analyser_calibration_due_at()
        if calib_due is not None and calib_due < time.time() and re.search(
            r"analyser|residual|turbidity|compliance", combined, re.IGNORECASE,
        ):
            return _verdict(
                "block",
                "analyser reading is stale — calibration is overdue; a "
                "reading from an out-of-calibration analyser cannot support "
                "a current figure",
            )
        if (
            DOSE_WORDS.search(combined)
            and strength_recorded_at is not None
            and live_state.delivered_at() is not None
            and live_state.delivered_at() > strength_recorded_at
        ):
            return _verdict(
                "block",
                "chemical strength is stale — a new delivery has occurred "
                "since this figure was recorded; strength must be "
                "re-verified EACH delivery",
            )

    # ---- evidence standard: REJECT_AS_PROOF --------------------------------
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

    # ---- derivation guard ---------------------------------------------------
    carried = _similar_plant_carry(combined)
    if carried:
        return _verdict(
            "block",
            "never-allowed derivation: carrying a figure from a similar "
            f"plant ({carried}) [PLANT TRAP: a figure from a similar plant "
            "does not transfer without independent verification]",
        )
    for name, pattern, reason in DERIVATION_GUARD:
        if pattern.search(combined):
            return _verdict("block", f"{reason} [{name}]")

    # ---- INV-5 CONFLICT REFUSE ----------------------------------------------
    # Checked ahead of the other invariants: if two sources disagree on a
    # limit, nothing else about that limit matters until the conflict itself
    # is surfaced. This is a distinct invariant — it never picks a winner.
    conflict = _conflict(limit_sources)
    if conflict:
        names = [src for _, sources in conflict for src in sources]
        return _verdict(
            "refused",
            "INV-5 violation: conflicting limits from "
            f"{names[0]} and {names[1]} — REFUSE and report both; this "
            "invariant does not pick a winner between a permit and the "
            "underlying code",
        )

    # ---- INV-1 CT QUALIFIERS -------------------------------------------------
    if CT_VALUE_WORDS.search(answer):
        has_temp = ct_temperature_c is not None or bool(_TEMP_MENTION.search(answer))
        has_ph = ct_ph is not None or bool(_PH_MENTION.search(answer))
        has_disinfectant = bool(disinfectant) or bool(_DISINFECTANT_MENTION.search(answer))
        has_organism = bool(organism) or bool(_ORGANISM_MENTION.search(answer))
        has_log_target = log_target is not None or bool(_LOG_TARGET_MENTION.search(answer))
        missing = []
        if not has_temp:
            missing.append("temperature")
        if not has_ph:
            missing.append("pH")
        if not has_disinfectant:
            missing.append("disinfectant")
        if not has_organism:
            missing.append("organism")
        if not has_log_target:
            missing.append("log target")
        if missing:
            return _verdict(
                "block",
                "INV-1 violation: CT value without " + ", ".join(missing)
                + ". A CT value without temperature, pH, disinfectant, "
                "organism AND log target cannot be checked against the "
                "correct row of the CT table",
            )

    # ---- INV-2 CONTACT-TIME BASIS --------------------------------------------
    if CONTACT_TIME_WORDS.search(answer):
        effective_basis = contact_time_basis or _basis_from_text(answer)
        t10_is_required = bool(t10_required) or bool(_T10_REQUIRED_MENTION.search(answer))
        if t10_is_required and effective_basis == "theoretical":
            return _verdict(
                "block",
                "INV-2 violation: theoretical detention time used where a "
                "T10 tracer study is required — REJECT_AS_PROOF: theoretical "
                "detention does not prove contact time when T10 is required "
                "[theoretical-detention-where-t10-required]",
            )
        has_basis = (effective_basis in CONTACT_TIME_BASIS)
        has_flow = flow is not None or bool(_FLOW_MENTION.search(answer))
        has_tank_level = tank_level_assumed is not None or bool(_TANK_LEVEL_MENTION.search(answer))
        missing = []
        if not has_basis:
            missing.append("contact_time_basis (theoretical|T10|tracer)")
        if not has_flow:
            missing.append("flow")
        if not has_tank_level:
            missing.append("tank level assumed")
        if missing:
            return _verdict(
                "block",
                "INV-2 violation: contact time without " + ", ".join(missing)
                + ". A contact time without its basis, the flow it applies "
                "at, and the tank level assumed is not a usable figure",
            )

    # ---- INV-3 DOSE BASIS -----------------------------------------------------
    if DOSE_WORDS.search(answer):
        has_dose_basis = (dose_basis in DOSE_BASIS) or bool(_DOSE_BASIS_MENTION.search(answer))
        has_delivered_strength = delivered_strength is not None or bool(
            _DELIVERED_STRENGTH_MENTION.search(answer)
        )
        missing = []
        if not has_dose_basis:
            missing.append("dose_basis (as_product|as_active)")
        if not has_delivered_strength:
            missing.append("delivered strength")
        if missing:
            return _verdict(
                "block",
                "INV-3 violation: dose without " + " and ".join(missing)
                + ". A dose without its basis and the delivered, measured "
                "strength is not a usable figure",
            )

    # ---- INV-4 LIMIT QUALIFIER -------------------------------------------------
    if LIMIT_WORDS.search(answer):
        has_avg = averaging_basis is not None or bool(_AVERAGING_MENTION.search(answer))
        has_freq = monitoring_frequency is not None or bool(_FREQUENCY_MENTION.search(answer))
        has_reg = bool(regulation) or bool(_REGULATION_MENTION.search(answer))
        missing = []
        if not has_avg:
            missing.append("averaging basis")
        if not has_freq:
            missing.append("monitoring frequency")
        if not has_reg:
            missing.append("regulation")
        if missing:
            return _verdict(
                "block",
                "INV-4 violation: limit without " + ", ".join(missing)
                + ". A limit without its averaging basis, monitoring "
                "frequency and named regulation cannot be checked against a "
                "reading",
            )

    return _verdict("pass")


def gate_answer(
    query: str,
    answer: str,
    *,
    live_state: Optional[PlantState] = None,
    ct_temperature_c: Optional[float] = None,
    ct_ph: Optional[float] = None,
    disinfectant: Optional[str] = None,
    organism: Optional[str] = None,
    log_target: Optional[float] = None,
    contact_time_basis: Optional[str] = None,
    flow: Optional[float] = None,
    tank_level_assumed: Optional[Any] = None,
    t10_required: bool = False,
    dose_basis: Optional[str] = None,
    delivered_strength: Optional[float] = None,
    strength_recorded_at: Optional[float] = None,
    averaging_basis: Optional[str] = None,
    monitoring_frequency: Optional[str] = None,
    regulation: Optional[str] = None,
    limit_sources: Optional[Sequence[Dict[str, Any]]] = None,
    evidence: Optional[Sequence[str]] = None,
    retrieval: Optional[Any] = None,
    tracer_or_basis_changed_since: bool = False,
    permit_changed_since: bool = False,
    manual_revised_since: bool = False,
) -> Dict[str, Any]:
    """Gate one answer through the full invariant pipeline.

    ``retrieval``, when supplied, lets a caller prove the scope refusals fire
    BEFORE any retrieval happens: the refusal returns first and retrieval is
    never invoked. Every verdict comes from ``_evaluate_invariants`` — there
    is no other path, and no flag skips it.
    """
    return _evaluate_invariants(
        query=query,
        answer=answer,
        live_state=live_state,
        ct_temperature_c=ct_temperature_c,
        ct_ph=ct_ph,
        disinfectant=disinfectant,
        organism=organism,
        log_target=log_target,
        contact_time_basis=contact_time_basis,
        flow=flow,
        tank_level_assumed=tank_level_assumed,
        t10_required=t10_required,
        dose_basis=dose_basis,
        delivered_strength=delivered_strength,
        strength_recorded_at=strength_recorded_at,
        averaging_basis=averaging_basis,
        monitoring_frequency=monitoring_frequency,
        regulation=regulation,
        limit_sources=limit_sources,
        evidence=list(evidence or []),
        retrieval=retrieval,
        tracer_or_basis_changed_since=tracer_or_basis_changed_since,
        permit_changed_since=permit_changed_since,
        manual_revised_since=manual_revised_since,
    )
