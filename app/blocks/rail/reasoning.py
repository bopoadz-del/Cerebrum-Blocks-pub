"""Railway & Metro Construction — domain module for the shared kit_engine.

The gate itself is declarative now: app/blocks/rail/manifest.yaml (vocabulary)
plus invariants.yaml (records), evaluated by app.blocks.kit_engine. Nothing in
the evaluator knows what a twist limit or a chainage is; this module supplies
the pieces the evaluator does not, and that the shared kinds cannot express:

  * TrackBasis   the track/civils design-basis LOADER (design_basis.yaml),
                  kept for interview/provenance bookkeeping — the values are
                  never consulted by the gate, only reported as gaps.
  * TrackState   the two-source live-state model (possession/signalling
                  system + manual log), reused by app.blocks.rail_reasoning
                  to build Figures and to surface live preconditions.
  * word-pattern regexes that classify a query/answer into the kit's
    vocabulary (extract_figures, in the portable spec's host-contract sense —
    the host, not the evaluator, knows the words for "twist limit").
  * DERIVATION_GUARD: four never-allowed inferences with NO declarative home
    in this engine. `derivation` (invariants.py) only checks stated-arithmetic
    consistency and same-quantity self-contradiction; neither is a hook for an
    arbitrary "forbidden phrase" pattern per record. These four stay
    host-side, evaluated directly against the combined query+answer+evidence
    text, exactly as before. (The other two never-allowed inferences — the
    category carry and the asset carry — DO have a declarative home: the
    `provenance` kind's carry-verb + distinct-value check, INV-RAIL-CATEGORY-
    CARRY / INV-RAIL-ASSET-CARRY in invariants.yaml.)
"""
from __future__ import annotations

import pathlib
import re
import time
from typing import Any, Dict, List, Optional

import yaml

_DESIGN_BASIS_PATH = pathlib.Path(__file__).parent / "design_basis.yaml"

#: Every design-basis figure carries these. A null VALUE is legal — the
#: interview has not run. A missing QUALIFIER is not: half-qualified is how a
#: maintenance-tier limit answers a safety-tier question.
MANDATORY_QUALIFIERS = (
    "value",
    "unit",
    "route",
    "line",
    "category",
    "tier",
    "SFT_verified_date",
    "method",
    "disturbed_since",
    "envelope_type",
    "line_speed",
    "source",
    "revision",
    "date",
)

TIERS = ("design", "maintenance", "safety")
CATEGORIES = ("plain_line", "switches_and_crossings", "bridge_approach", "tunnel")

#: Clearance qualifiers, supplied at call time — a clearance is assessed
#: against the geometry in force, not carried from the design basis alone.
CLEARANCE_QUALIFIERS = ("envelope_type", "cant", "curve_radius")

#: TBM face-pressure qualifiers, supplied at call time as a chainage-specific
#: schedule. A schedule with no band, or no ground basis, is not a schedule.
TBM_QUALIFIERS = ("chainage_min_m", "chainage_max_m", "ground_basis")


class ManifestError(ValueError):
    """A design-basis figure arrived without its mandatory qualifiers."""


class TrackBasis:
    """The track/civils design basis, loaded from design_basis.yaml.

    The loader is the first gate. It refuses at LOAD time — not at answer
    time — so a half-qualified figure cannot sit in the design basis waiting
    to be quoted. The refusal names the figure and every key it lacks.

    This is provenance/interview bookkeeping only: the gate (manifest.yaml +
    invariants.yaml, via kit_engine) never reads a value out of this loader.
    """

    def __init__(self, design_basis_path: Optional[pathlib.Path] = None) -> None:
        path = design_basis_path or _DESIGN_BASIS_PATH
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.source = raw.get("source")
        self.scope = raw.get("scope")
        self.interview_status = raw.get("interview_status")
        self._entries: Dict[str, Dict[str, Any]] = {}
        for name, entry in (raw.get("design_basis") or {}).items():
            if not isinstance(entry, dict):
                raise ManifestError(
                    f"design-basis figure '{name}' is not a qualified entry; "
                    f"every figure is a mapping carrying "
                    f"{', '.join(MANDATORY_QUALIFIERS)}"
                )
            missing = [key for key in MANDATORY_QUALIFIERS if key not in entry]
            if missing:
                raise ManifestError(
                    f"design-basis figure '{name}' is partially qualified — "
                    f"missing {', '.join(missing)}. A figure without its "
                    f"qualifiers cannot be quoted against any question"
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


class TrackState:
    """Current track state. Requires BOTH sources:

    - ``possession_system``: what the signalling / possession system holds —
      possessions taken, isolations, TSRs in force, protection arrangements.
    - ``manual_log``: what the possession system does NOT see — manual
      disturbance records (tamping, renewal, undercutting, rail work) and
      any local protection arranged on top of the system.

    The possession system is itself a single point of failure: if it is
    unreachable the track state is UNKNOWN. There is no design-basis
    fallback for live state — a design figure presented as a current state
    is the failure this gate exists to stop.
    """

    _MAX_AGE_SECONDS = 3600

    def __init__(
        self,
        possession_system: Optional[Dict[str, Any]],
        manual_log: Optional[Dict[str, Any]],
        fetched_at: Optional[float] = None,
    ) -> None:
        self.possession_system = possession_system
        self.manual_log = manual_log
        self.fetched_at = fetched_at if fetched_at is not None else time.time()

    def both_sources_present(self) -> bool:
        return self.possession_system is not None and self.manual_log is not None

    def fresh(self) -> bool:
        return (time.time() - self.fetched_at) <= self._MAX_AGE_SECONDS

    def possessions_in_force(self) -> List[Any]:
        return list((self.possession_system or {}).get("possessions") or [])

    def isolations_in_force(self) -> List[Any]:
        return list((self.possession_system or {}).get("isolations") or [])

    def tsrs_in_force(self) -> List[Any]:
        return list((self.possession_system or {}).get("tsrs") or [])

    def protection_arrangements(self) -> List[Any]:
        return list((self.manual_log or {}).get("protection_arrangements") or [])

    def track_disturbed_since(self) -> Optional[float]:
        """Timestamp of a manual-log disturbance event, if any.

        This is a live-state-sourced disturbance signal — distinct from the
        caller-supplied ``disturbed_since`` flag. Either one is enough to
        make a figure stale; neither one is optional to check.
        """
        return (self.manual_log or {}).get("disturbed_at")


# --------------------------------------------------------------------------
# extract_figures vocabulary — the host's word lists, not the evaluator's
# --------------------------------------------------------------------------

GEOMETRY_LIMIT_WORDS = re.compile(
    r"twist\s+limit|cant\s+deficiency\s+limit|alignment\s+limit|"
    r"gauge\s+limit|geometry\s+limit|passing\s+value|intervention\s+value|"
    r"immediate\s+action\s+limit",
    re.IGNORECASE,
)

SFT_WORDS = re.compile(
    r"\bSFT\b|stress[-\s]?free\s+temperature|stressing\s+temperature",
    re.IGNORECASE,
)

#: "buckl*" alone — SFT and handback speed are classified separately, first,
#: so a statement naming either of those is not double-counted here.
BUCKLING_WORDS = re.compile(r"buckl\w*|stress(?:ing)?\s+(?:the\s+)?rail", re.IGNORECASE)

HANDBACK_SPEED_WORDS = re.compile(r"handback\s+speed|hand\s*back\s+speed", re.IGNORECASE)

CLEARANCE_WORDS = re.compile(
    r"clearance|structure\s+gauge|kinematic\s+envelope|gauging\s+assessment|"
    r"\bgauging\b",
    re.IGNORECASE,
)

FACE_PRESSURE_WORDS = re.compile(
    r"face\s+pressure|\bTBM\b|tunnel\s+boring",
    re.IGNORECASE,
)

TRIGGER_WORDS = re.compile(
    r"\btrigger\b|settlement\s+trigger|movement\s+trigger", re.IGNORECASE
)

TSR_WORDS = re.compile(r"\bTSR\b|temporary\s+speed\s+restriction", re.IGNORECASE)

BALLAST_WORDS = re.compile(r"\bballast\b", re.IGNORECASE)

GEOMETRY_RECORDING_WORDS = re.compile(
    r"geometry\s+recording|track\s+geometry\s+(?:record|reading|run)",
    re.IGNORECASE,
)

LIVE_STATE_WORDS = re.compile(
    r"possession|isolation|\bTSR\b|temporary\s+speed\s+restriction|"
    r"protection\s+arrangement|current\s+(?:state|status)|right\s+now|"
    r"four[-\s]?foot|adjacent\s+line|handback|hand\s*back|"
    r"disturbance\s+status",
    re.IGNORECASE,
)

#: A range needs two numbers, or two named bounds. One number is not a band.
NUMBER = re.compile(r"-?\d+(?:\.\d+)?")

CATEGORY_TOKEN = re.compile(
    r"plain[-_\s]?line|switches?[-_\s]+and[-_\s]+crossings|s\s*&\s*c|"
    r"bridge[-_\s]+approach|tunnel",
    re.IGNORECASE,
)

ASSET_TOKEN = re.compile(r"building\s+\w+|structure\s+\w+|asset\s+\w+", re.IGNORECASE)

CARRY_VERB = re.compile(
    r"\bsame\b|\bapply\b|\bapplies\b|\bcarry\b|\bcarried\b|\breuse\b|"
    r"\bas\s+well\b|\buse\s+the\b|\bequivalent\b|\btransfer\b|"
    r"\binterpolat\w*\b|\bacross\b|\bbetween\b",
    re.IGNORECASE,
)


def distinct_mentions(pattern: "re.Pattern", text: str) -> List[str]:
    """Distinct values named in *text*, normalised for comparison.

    Used only to decide WHETHER to build a figure at all (a carry-verb plus
    two distinct category/asset mentions), not to judge the carry itself —
    that judgement is the `provenance` kind's, in invariants.yaml.
    """
    found: List[str] = []
    for match in pattern.finditer(text or ""):
        norm = re.sub(r"\s+", " ", match.group(0).lower()).strip()
        if norm not in found:
            found.append(norm)
    return found


# --------------------------------------------------------------------------
# the four never-allowed inferences with no declarative home (see module
# docstring). Each blocks under its own name — "blocked" alone teaches
# nobody anything.
# --------------------------------------------------------------------------
DERIVATION_GUARD: List[tuple] = [
    (
        "SFT from installation temperature",
        re.compile(
            r"(?=.*(?:\bSFT\b|stress[-\s]?free\s+temperature))"
            r"(?=.*installation\s+temperature)"
            r"(?=.*(?:infer|derive|calculate|assume|equals?|based\s+on|from\s+the))",
            re.IGNORECASE),
        "never-allowed derivation: inferring the stress-free temperature from "
        "the installation temperature",
    ),
    (
        "scale clearances off drawings",
        re.compile(
            r"(?=.*clearance)(?=.*(?:scale|scaled|scaling))(?=.*drawing)",
            re.IGNORECASE),
        "never-allowed derivation: scaling a clearance figure off a design "
        "drawing instead of a gauging assessment — a design drawing is not "
        "acceptable evidence (REJECT_AS_PROOF) for a clearance figure",
    ),
    (
        "carry face pressure from similar drive",
        re.compile(
            r"(?=.*face\s+pressure)(?=.*similar\s+drive)"
            r"(?=.*(?:apply|use|same|carry|equivalent))",
            re.IGNORECASE),
        "never-allowed derivation: carrying face pressure from a similar "
        "drive — a schedule is chainage-specific, not drive-specific",
    ),
    (
        "carry twist without base length",
        re.compile(
            r"(?=.*\btwist\b)(?=.*\bwithout\b)(?=.*\bbase\s+length\b)",
            re.IGNORECASE),
        "never-allowed derivation: carrying a twist figure without stating "
        "the base length it was measured over — twist is meaningless without it",
    ),
]
