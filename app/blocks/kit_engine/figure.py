"""The Figure — what a host hands the evaluator — and the Outcome it gets back.

A vertical platform answers with FIGURES. A figure is usable only if it is
grounded, complete, dimensioned, authorised, its own, current, in scope and
self-consistent. Each of those is a property that can fail, and each failure is
one invariant kind. This module is the data the kinds read.

``span`` is what makes surgical repair possible: a finding on one figure can
replace that figure rather than refusing the whole answer, which matters when a
long answer carries one bad number.

``origin`` is load-bearing for a rule that holds in every domain: **never refuse
the operator's own figure.** If they typed the rate, it is authoritative input,
not a claim to check — flag it and proceed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

ORIGINS = ("tool", "document", "model", "operator")

#: Severities, weakest first. `annotate` notes it, `flag` marks it and proceeds,
#: `refuse` stops the answer (or replaces the figure, when the span allows).
SEVERITIES = ("annotate", "flag", "refuse")


@dataclass
class Figure:
    """One figure in an answer, with everything known about where it came from."""

    quantity: str
    value: Any = None
    unit: Optional[str] = None
    origin: str = "model"
    source_id: Optional[str] = None
    source_class: Optional[str] = None
    revision: Optional[str] = None
    effective_date: Optional[str] = None
    qualifiers: Dict[str, Any] = field(default_factory=dict)
    #: Where it sits in the answer, for surgical repair: {"start": .., "end": ..}
    span: Optional[Dict[str, int]] = None
    #: The prose around the figure. Read ONLY by the kinds that must see words
    #: (unit discipline, derivation consistency). No kind infers a qualifier
    #: from it — inferring a qualifier from prose is the defect, not the fix.
    text: str = ""
    #: The entity the QUESTION is about, when the host knows it. Provenance
    #: compares the figure's own entity against this; it does not guess from
    #: prose. Keys are qualifier field names (runway_designator, contract, ...).
    asked_about: Dict[str, Any] = field(default_factory=dict)
    #: What KIND of claim this figure is making (dose, code_requirement,
    #: position, bearing, historical, work_recommendation ...). An invariant may
    #: narrow to one via applies_to.claim_class. The host sets it; no invariant
    #: guesses it from prose, because guessing the claim class is the defect.
    claim_class: Optional[str] = None
    #: Named derivations the host detected while producing the figure, matched
    #: against a provenance or derivation record's `forbid` list.
    derivations: List[str] = field(default_factory=list)
    #: Named blocking conditions the host detected (sources_conflict,
    #: calculation_hidden, product_not_reversible ...), matched against `block_if`.
    conditions: List[str] = field(default_factory=list)
    #: Steps the host actually showed, matched against `requires_steps`.
    steps: List[str] = field(default_factory=list)
    #: For a two-sided band: {"min": .., "max": .., "source_id_min": ..,
    #: "source_id_max": ..}. `same_source` compares the last two.
    bounds: Dict[str, Any] = field(default_factory=dict)

    def known(self, name: str) -> bool:
        """A key present with None counts as NOT known.

        "We have a field for it" is not "we know it", and treating an explicit
        null as a value is how a half-qualified figure passes a completeness
        check.
        """
        return self.qualifiers.get(name) is not None

    def missing(self, names: Sequence[str]) -> List[str]:
        return [name for name in names if not self.known(name)]

    @property
    def is_operators_own(self) -> bool:
        return self.origin == "operator"


@dataclass
class Finding:
    """One invariant's judgement on one figure."""

    invariant_id: str
    kind: str
    severity: str
    message: str
    quantity: str = ""
    missing: List[str] = field(default_factory=list)
    span: Optional[Dict[str, int]] = None
    #: Set when the severity was softened because the figure is the operator's.
    softened_from: Optional[str] = None

    @property
    def stops_the_answer(self) -> bool:
        return self.severity == "refuse"

    def as_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "invariant": self.invariant_id,
            "kind": self.kind,
            "severity": self.severity,
            "message": self.message,
        }
        if self.quantity:
            out["quantity"] = self.quantity
        if self.missing:
            out["missing"] = list(self.missing)
        if self.span:
            out["span"] = dict(self.span)
        if self.softened_from:
            out["softened_from"] = self.softened_from
        return out


@dataclass
class Outcome:
    """What the host applies: annotate, flag or refuse, plus why."""

    verdict: str
    findings: List[Finding] = field(default_factory=list)
    hook: str = ""
    kit: str = ""
    #: True when the budget cap was hit and checks were skipped. A skipped check
    #: is NOT a pass, and the host must not present it as one.
    incomplete: bool = False
    skipped: int = 0

    @property
    def blocked_reason(self) -> str:
        return "; ".join(f.message for f in self.findings if f.stops_the_answer)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "hook": self.hook,
            "kit": self.kit,
            "findings": [f.as_dict() for f in self.findings],
            "blocked_reason": self.blocked_reason,
            "incomplete": self.incomplete,
            "skipped_checks": self.skipped,
        }


def verdict_for(findings: Sequence[Finding]) -> str:
    if any(f.stops_the_answer for f in findings):
        return "refused"
    if any(f.severity == "flag" for f in findings):
        return "flagged"
    if findings:
        return "annotated"
    return "pass"
