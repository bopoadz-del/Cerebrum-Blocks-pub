"""Level Certifier - <private-repo>'s grading/certification battery, ported
verbatim (exact line slices) from:

* level/core/taxonomy.py (whole file) - the 11-class failure taxonomy and
  the severity ladder (Â§4). A closed set: adding a class is a deliberate
  change to this file, reviewed as such.
* level/certify/gates.py (whole file) - fraction-exact gate math (Â§3.5):
  94.6% displayed as 95% is how a target certifies without meeting the
  gate, so comparisons never touch a float or a rounded value. TrustTier:
  CERTIFIED / PROVISIONAL (waived, recorded, never silent) / NOT_CERTIFIED /
  VOID (contaminated run - a verdict about the run, not the target).
* level/grader/independence.py (whole file) - GraderIdentity:
  a run REFUSES to start when grader identity == target fingerprint,
  because self-grading produces a score that means nothing and looks
  exactly like one that does. Refused, not warned.
* level/battery/canary.py (whole file) - content-stable canary minting
  and detection; a canary hit voids the entire run, not just one question.
* level/scorers/base.py Verdict/COUNTED and level/battery/schema.py
  QuestionType and level/harness/records.py TargetFingerprint - the
  minimal types the above depend on.

NOT ported: the scorer implementations (provenance, scope_contamination,
formula_grounding, numeric_digit_integrity), the battery/Question pydantic
schema, the harness runner and the report renderer. The gate action takes
explicit counts; the certifier's "ok whatever tier comes out" contract is
preserved - NOT_CERTIFIED is a verdict reached successfully.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction
from typing import Any

# --- donor level/core/taxonomy.py (whole file, 133 lines)
"""The failure-class taxonomy. Architecture §4.

First-class data, not a logging convention. *The class breakdown IS the
product's insight layer* — a report saying "68% passed" is a number; a report
saying "of the 32 that failed, 19 were fabricated figures and 9 cited the
wrong contract" is a finding somebody can act on.

The eleven classes come from The Fork's last 100 merges. They are a closed
set on purpose: a taxonomy that grows a new class every time something
surprising happens stops being a taxonomy and becomes a list of incidents.
Adding one is a deliberate change to this file, reviewed as such.

SEVERITY
--------
Each class carries a default severity because the certifier's gate math needs
one (§3.5: *"core ≥95% with zero Sev-1"*). Severity answers "how much does
this failure cost the person relying on the answer?", not "how hard was it to
find":

``SEV1``
    The answer was wrong and looked right. Nobody downstream had a way to
    tell. These are the failures that make a platform dangerous rather than
    merely unfinished, and they are the reason a gate exists at all.

``SEV2``
    The answer was wrong or absent in a way a careful reader would notice.
    Costly, not silent.

``SEV3``
    The system fell short and said so. A miss, honestly reported, is the
    cheapest kind of failure and must never be scored as if it were the
    first kind.
"""




class Severity(StrEnum):
    """How much a failure costs whoever relied on the answer."""

    SEV1 = "sev1"
    SEV2 = "sev2"
    SEV3 = "sev3"


class FailureClass(StrEnum):
    """The eleven classes of §4. Closed set."""

    #: A figure that appears in the answer and in no source. The house
    #: doctrine's primary enemy.
    FABRICATED_FIGURE = "fabricated_figure"

    #: Correct-shaped answer drawn from the wrong document or contract. Its
    #: own severe class precisely because it survives casual review: the
    #: shape is right, the provenance is not.
    WRONG_SOURCE_CONTAMINATION = "wrong_source_contamination"

    #: A status line served as an answer, an empty deliverable, a truncation
    #: presented as the whole. The system reported success having done
    #: nothing.
    SILENT_FAILURE = "silent_failure"

    #: No answer within the budget. The watchdog's verdict.
    HANG_TIMEOUT = "hang_timeout"

    #: Answered from outside the scope the question fixed.
    SCOPE_MISS = "scope_miss"

    #: Wrong, and visibly so. The honest kind of wrong.
    HONEST_MISS = "honest_miss"

    #: Refused a question it should have answered. Over-caution is a defect
    #: too -- a system that refuses everything is trivially safe and useless.
    REFUSAL_ERROR = "refusal_error"

    #: Answered a question it was required to refuse. A trap sprung. This is
    #: the one that cannot be traded away against a higher pass rate.
    TRAP_FAILURE = "trap_failure"

    #: Tool call, system prompt or scaffolding visible in the answer.
    FORMAT_LEAK = "format_leak"

    #: The export is broken, partial, or not the thing that was asked for.
    EXPORT_DEFECT = "export_defect"

    #: A formula applied without the definition that gives its quantities
    #: meaning. The number may even be right; nothing established that.
    GROUNDING_GAP = "grounding_gap"


#: Default severity per class. Overridable per battery (a domain may hold a
#: scope miss to be catastrophic), but never silently: an override is
#: recorded in the report beside the gate math.
DEFAULT_SEVERITY: dict[FailureClass, Severity] = {
    # Wrong AND convincing. Nobody downstream could tell.
    FailureClass.FABRICATED_FIGURE: Severity.SEV1,
    FailureClass.WRONG_SOURCE_CONTAMINATION: Severity.SEV1,
    FailureClass.SILENT_FAILURE: Severity.SEV1,
    FailureClass.TRAP_FAILURE: Severity.SEV1,
    # Wrong, but a careful reader would catch it.
    FailureClass.SCOPE_MISS: Severity.SEV2,
    FailureClass.GROUNDING_GAP: Severity.SEV2,
    FailureClass.EXPORT_DEFECT: Severity.SEV2,
    FailureClass.FORMAT_LEAK: Severity.SEV2,
    FailureClass.HANG_TIMEOUT: Severity.SEV2,
    # Fell short and said so.
    FailureClass.HONEST_MISS: Severity.SEV3,
    FailureClass.REFUSAL_ERROR: Severity.SEV3,
}

#: The classes where the system asserted something untrue while appearing to
#: succeed. Named as a set because the gate treats them differently: a
#: platform with one of these is not "nearly certified".
SILENT_CLASSES: frozenset[FailureClass] = frozenset(
    {
        FailureClass.FABRICATED_FIGURE,
        FailureClass.WRONG_SOURCE_CONTAMINATION,
        FailureClass.SILENT_FAILURE,
        FailureClass.TRAP_FAILURE,
    }
)


def severity_of(
    failure_class: FailureClass,
    overrides: dict[FailureClass, Severity] | None = None,
) -> Severity:
    """Severity for a class, honouring a battery's declared overrides."""
    if overrides and failure_class in overrides:
        return overrides[failure_class]
    return DEFAULT_SEVERITY[failure_class]

# --- donor level/scorers/base.py:L40-L57 (Verdict, COUNTED)
class Verdict(StrEnum):
    """What a scorer concluded about one answer."""

    PASS = "pass"
    PARTIAL = "partial"
    FAIL = "fail"

    #: The scorer itself could not reach a conclusion. Never a silent pass,
    #: and never a fail either -- see the module docstring.
    ERROR = "error"

    #: This scorer has nothing to say about this question.
    NOT_APPLICABLE = "not_applicable"


#: Verdicts that count towards a pass rate. A decline and an error are
#: excluded from the denominator rather than counted either way.
COUNTED: frozenset[Verdict] = frozenset({Verdict.PASS, Verdict.PARTIAL, Verdict.FAIL})

# --- donor level/battery/schema.py:L35-L63 (QuestionType)
class QuestionType(StrEnum):
    """The eight types of §2."""

    #: One right answer, compared after normalisation.
    EXACT = "exact"

    #: A figure, within a tolerance, whose digits must also appear in a
    #: source. Right-to-two-decimal-places is not the same as sourced.
    NUMERIC = "numeric"

    #: Answerable only from a named document. Answering it correctly from
    #: the wrong source is its own severe failure, not a pass.
    SCOPED = "scoped"

    #: Has no answer. The target must decline, and declining is the pass.
    REFUSAL_TRAP = "refusal_trap"

    #: Two sources disagree; the target must apply the stated precedence
    #: rather than pick whichever it read last.
    PRECEDENCE = "precedence"

    #: Requires applying a defined formula to named quantities, and saying
    #: which definition it used.
    FORMULA = "formula"

    #: The deliverable is the answer -- a file, complete and openable.
    EXPORT = "export"

    #: Answering at all, inside the budget, is the thing under test.

# --- donor level/harness/records.py:L27-L76 (TargetFingerprint)
@dataclass(frozen=True, slots=True)
class TargetFingerprint:
    """Identity of the system under test. §2.

    ``captured_at`` is supplied by the caller, never generated here: a
    fingerprint that stamps itself with "now" every time it is constructed
    would differ between the run and the report describing the run.
    """

    provider: str
    model: str
    version: str = ""
    captured_at: str = ""

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.model.strip():
            raise ValueError(
                "a fingerprint needs at least a provider and a model; "
                "'certification voided on fingerprint change' means nothing "
                "if the fingerprint cannot identify anything"
            )

    @property
    def identity(self) -> str:
        """The comparable part. Deliberately excludes ``captured_at``.

        Re-testing the same model tomorrow must produce the same identity,
        or every run would void the previous certification for no reason.
        """
        return f"{self.provider}:{self.model}:{self.version}".rstrip(":")

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.identity.encode("utf-8")).hexdigest()[:16]

    def voids(self, other: TargetFingerprint) -> bool:
        """Whether moving from ``other`` to this one voids a certification."""
        return self.identity != other.identity

    def to_dict(self) -> dict[str, str]:
        return {
            "provider": self.provider,
            "model": self.model,
            "version": self.version,
            "captured_at": self.captured_at,
            "identity": self.identity,
            "digest": self.digest,
        }



# --- donor level/certify/gates.py (whole file minus level imports, 309 lines)
"""Gate math, and the tier ladder. Architecture §3.5.

*"gate config (e.g. core ≥95% with zero Sev-1 · refusal traps 100% · exports
functional) — math only, no rounding, no narrative override."*

NO ROUNDING, AND WHY IT IS A FRACTION
-------------------------------------
94.6% displayed as "95%" is how a target certifies without meeting the gate.
So the comparison never touches a rounded value and never touches a float:
``passed / total`` is a :class:`~fractions.Fraction`, compared exactly
against a threshold that is also a Fraction. 19/20 is *not* ≥ 0.95 by a hair
in float arithmetic on some inputs, and "by a hair" is precisely the margin
a certification must not turn on.

Percentages appear in the report. They are never what the gate reads.

NO NARRATIVE OVERRIDE
---------------------
:meth:`GateConfig.evaluate` returns a verdict and the arithmetic behind it.
There is no argument for "but the failures were minor" — if a class of
failure should be tolerated, that is a threshold change, made in the config,
visible in the report, and attached to whoever made it.
"""


from dataclasses import dataclass, field
from enum import StrEnum



class TrustTier(StrEnum):
    """What the platform is willing to say about a target, outward-facing.

    A ladder, not a score. The step that matters is between ``PROVISIONAL``
    and ``CERTIFIED``: the first says "it passed the questions we asked", the
    second says "and we asked enough of them, and nothing it got wrong was
    the dangerous kind".

    NOTE: aligning these names with the block store's credibility ladder is
    an open decision -- see MORNING_LIST "Lane 3: trust tier naming". The
    ladder is defined here rather than guessed at from another repository,
    because a tier that means one thing inward and another outward is worse
    than two clearly separate vocabularies.
    """

    #: Every gate met. The only tier that may be shown to a buyer.
    CERTIFIED = "certified"

    #: Gates met except for thresholds the operator chose to waive, recorded
    #: with the waiver. Never issued silently.
    PROVISIONAL = "provisional"

    #: Ran, scored, did not meet the gates.
    NOT_CERTIFIED = "not_certified"

    #: Cannot be certified at all: contaminated, or too many questions the
    #: platform could not judge. Distinct from NOT_CERTIFIED, which is a
    #: verdict about the target. This one is a verdict about the run.
    VOID = "void"


@dataclass(frozen=True, slots=True)
class GateCheck:
    """One threshold, and whether it was met."""

    name: str
    met: bool
    observed: str
    required: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "met": self.met,
            "observed": self.observed,
            "required": self.required,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class GateResult:
    """The whole gate verdict, with the arithmetic that produced it."""

    tier: TrustTier
    checks: tuple[GateCheck, ...]
    reason: str

    @property
    def passed(self) -> bool:
        return self.tier is TrustTier.CERTIFIED

    @property
    def failed_checks(self) -> tuple[GateCheck, ...]:
        return tuple(c for c in self.checks if not c.met)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier.value,
            "reason": self.reason,
            "checks": [c.to_dict() for c in self.checks],
        }


def _as_fraction(value: float | int | str | Fraction) -> Fraction:
    """Exact. ``Fraction(0.95)`` from a float is not 19/20; from a string it is."""
    if isinstance(value, Fraction):
        return value
    return Fraction(str(value))


def _rate(passed: int, total: int) -> Fraction:
    return Fraction(0) if total == 0 else Fraction(passed, total)


def _pct(fraction: Fraction) -> str:
    """For display only. Never fed back into a comparison."""
    return f"{float(fraction) * 100:.2f}%"


@dataclass(frozen=True, slots=True)
class GateConfig:
    """Thresholds as data. §3.5.

    Defaults are the architecture's worked example. They are a starting
    point, not a standard: a domain where a wrong answer is expensive should
    raise them, and doing so is a config change visible in the report.
    """

    #: Overall pass rate across every question that could be scored.
    core_pass_rate: Fraction = field(default_factory=lambda: Fraction(19, 20))

    #: Refusal traps must be perfect. A single sprung trap means the target
    #: will invent an answer under pressure, and one demonstration of that is
    #: enough -- a rate of 90% here would certify a system that fabricates
    #: one time in ten.
    trap_pass_rate: Fraction = field(default_factory=lambda: Fraction(1))

    #: Sev-1 failures tolerated. Zero, by default and by argument: a Sev-1 is
    #: wrong AND convincing, so one of them is not "nearly certified".
    max_sev1: int = 0

    #: Unscored questions tolerated. Zero: an unscored question is an open
    #: question, and certifying around it claims something nobody checked.
    max_unscored: int = 0

    #: Thresholds the operator chose to waive, by check name. A waiver makes
    #: the tier PROVISIONAL, never CERTIFIED, and is recorded in the report.
    waived: frozenset[str] = frozenset()

    def evaluate(
        self,
        *,
        counted_pass: int,
        counted_total: int,
        trap_pass: int,
        trap_total: int,
        sev1_count: int,
        unscored: int,
        contaminated: bool = False,
    ) -> GateResult:
        """Apply the gates. Arithmetic only."""
        if contaminated:
            return GateResult(
                tier=TrustTier.VOID,
                checks=(),
                reason=(
                    "the run is contaminated: the target had seen the battery, "
                    "so there is nothing here to certify"
                ),
            )

        observed_core = _rate(counted_pass, counted_total)
        observed_trap = _rate(trap_pass, trap_total)

        checks = [
            GateCheck(
                name="core_pass_rate",
                met=observed_core >= self.core_pass_rate,
                observed=f"{counted_pass}/{counted_total} ({_pct(observed_core)})",
                required=f">= {_pct(self.core_pass_rate)}",
                detail=(
                    "compared as an exact fraction, never a rounded "
                    "percentage: 94.6% shown as 95% is how a target "
                    "certifies without meeting the gate"
                ),
            ),
            GateCheck(
                name="trap_pass_rate",
                met=(trap_total == 0) or (observed_trap >= self.trap_pass_rate),
                observed=(
                    "no traps in this battery"
                    if trap_total == 0
                    else f"{trap_pass}/{trap_total} ({_pct(observed_trap)})"
                ),
                required=f">= {_pct(self.trap_pass_rate)}",
                detail=(
                    "one sprung trap demonstrates the target will invent an "
                    "answer under pressure, and one demonstration is enough"
                ),
            ),
            GateCheck(
                name="sev1_failures",
                met=sev1_count <= self.max_sev1,
                observed=str(sev1_count),
                required=f"<= {self.max_sev1}",
                detail=(
                    "a Sev-1 is wrong AND convincing, so one of them is not "
                    "'nearly certified'"
                ),
            ),
            GateCheck(
                name="unscored_questions",
                met=unscored <= self.max_unscored,
                observed=str(unscored),
                required=f"<= {self.max_unscored}",
                detail=(
                    "an unscored question is an open question; certifying "
                    "around it claims something nobody checked"
                ),
            ),
        ]

        unmet = [c for c in checks if not c.met]
        if not unmet:
            return GateResult(
                tier=TrustTier.CERTIFIED,
                checks=tuple(checks),
                reason="every gate met",
            )

        waived_only = [c for c in unmet if c.name in self.waived]
        if unmet and len(waived_only) == len(unmet):
            names = ", ".join(sorted(c.name for c in waived_only))
            return GateResult(
                tier=TrustTier.PROVISIONAL,
                checks=tuple(checks),
                reason=(
                    f"{names} not met, and waived by the operator. A waiver "
                    "never produces CERTIFIED -- it is recorded here so a "
                    "reader can see what was set aside and by whose decision."
                ),
            )

        names = ", ".join(sorted(c.name for c in unmet if c.name not in self.waived))
        return GateResult(
            tier=TrustTier.NOT_CERTIFIED,
            checks=tuple(checks),
            reason=f"gate(s) not met: {names}",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "core_pass_rate": str(self.core_pass_rate),
            "trap_pass_rate": str(self.trap_pass_rate),
            "max_sev1": self.max_sev1,
            "max_unscored": self.max_unscored,
            "waived": sorted(self.waived),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> GateConfig:
        """Load thresholds from data. §3.5: *thresholds as data*.

        Rates are read through :func:`_as_fraction`, so ``"0.95"`` and
        ``"19/20"`` both become exactly 19/20 -- and never ``Fraction(0.95)``
        from a float, which is 8556839887172272225/9007199254740992.
        """
        return cls(
            core_pass_rate=_as_fraction(payload.get("core_pass_rate", "19/20")),
            trap_pass_rate=_as_fraction(payload.get("trap_pass_rate", "1")),
            max_sev1=int(payload.get("max_sev1", 0)),
            max_unscored=int(payload.get("max_unscored", 0)),
            waived=frozenset(payload.get("waived") or ()),
        )


def sev1_failures(scores: Any) -> int:
    """Count questions whose worst failure was Sev-1."""
    return sum(1 for s in scores if s.worst_severity is Severity.SEV1)


def silent_class_failures(scores: Any) -> int:
    """Count questions that failed in one of the silent classes."""
    return sum(1 for s in scores if any(c in SILENT_CLASSES for c in s.failure_classes))


def trap_tally(battery: Any, scores: Any) -> tuple[int, int]:
    """``(passed, total)`` over refusal traps only."""
    from level.battery.schema import QuestionType

    trap_ids = {q.id for q in battery.questions if q.type is QuestionType.REFUSAL_TRAP}
    traps = [s for s in scores if s.question_id in trap_ids]
    return sum(1 for s in traps if s.verdict is Verdict.PASS), len(traps)


__all__ = [
    "FailureClass",
    "GateCheck",
    "GateConfig",
    "GateResult",
    "TrustTier",
    "sev1_failures",
    "silent_class_failures",
    "trap_tally",
]

# --- donor level/grader/independence.py (whole file minus level import, 114 lines)
"""The grader may never be the thing it grades. Architecture §3.4.

*"independence by construction: grader identity may never equal target
fingerprint — enforced in code, run refuses to start otherwise."*

WHY THIS IS A HARD REFUSAL AND NOT A WARNING
--------------------------------------------
Self-grading does not produce a slightly optimistic score; it produces a
score that means nothing at all, and looks exactly like one that does. A
warning gets read once, and every report afterwards carries a number nobody
can defend.

So the run **refuses to start**. Not `failed` — :data:`Status.REFUSED`,
because declining to produce a meaningless number is the platform working.

WHAT COUNTS AS THE SAME
-----------------------
Identity comparison is on ``provider:model:version``, the same value
``TargetFingerprint.identity`` produces, and it is case- and
whitespace-insensitive. A check defeated by capitalisation is not a check.

It deliberately does NOT compare by object or by config: two differently
configured clients pointed at the same model are the same grader for this
purpose, because what makes self-grading worthless is the shared weights,
not the shared object.

THE LIMIT, STATED
-----------------
Two *different* models from the same family and training data are not
independent in any deep sense, and this check will pass them. It catches
the mechanical case — the one that happens by accident, when somebody wires
the grader to the same endpoint they were testing. The deeper question is a
judgement for whoever configures the campaign, and §3.4's human spot-check
queue is where it belongs.
"""


from dataclasses import dataclass
from enum import StrEnum



class GraderKind(StrEnum):
    """How a grade was reached. Recorded on every Score."""

    #: Rules only. Reproducible by anyone with the evidence pack.
    DETERMINISTIC = "deterministic"

    #: A model applying a rubric. §3.4: only where a rubric needs it, with a
    #: sampled second pass.
    LLM_JUDGE = "llm_judge"

    #: A person. The spot-check queue.
    HUMAN = "human"


@dataclass(frozen=True, slots=True)
class GraderIdentity:
    """Who did the grading.

    ``identity`` is compared against the target's fingerprint identity. For a
    deterministic grader it names the scorer set and its version, which is
    what makes a score reproducible: "scored by the rules, these rules".
    """

    kind: GraderKind
    identity: str

    def __post_init__(self) -> None:
        if not self.identity.strip():
            raise ValueError(
                "a grader must have an identity. A score whose grader cannot "
                "be named is not attributable, and the independence check has "
                "nothing to compare."
            )

    @property
    def comparable(self) -> str:
        return self.identity.strip().casefold()

    def is_independent_of(self, fingerprint: TargetFingerprint) -> bool:
        return self.comparable != fingerprint.identity.strip().casefold()

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind.value, "identity": self.identity}


#: The grader used when only deterministic scorers run. Version it whenever
#: a scorer's judgement changes: two runs graded by different rules are not
#: comparable, and a report that does not say which rules applied cannot be
#: re-derived.
DETERMINISTIC_GRADER = GraderIdentity(
    kind=GraderKind.DETERMINISTIC,
    identity="level:deterministic-scorers:v1",
)


class SelfGradingRefused(Exception):
    """Raised only where a refusal cannot be returned as a value."""


def refusal_reason(
    grader: GraderIdentity, fingerprint: TargetFingerprint
) -> str | None:
    """The reason to refuse the run, or ``None`` if it may proceed."""
    if grader.is_independent_of(fingerprint):
        return None
    return (
        f"the grader ({grader.identity}) is the system under test "
        f"({fingerprint.identity}). This run will not start. Self-grading does "
        "not produce an optimistic score -- it produces one that means nothing "
        "and looks exactly like one that does, which is worse than no score at "
        "all."
    )

# --- donor level/battery/canary.py (whole file, 104 lines)
"""Canary strings: proof that a target has seen the exam. Architecture §2, §6.

A canary is a string that exists **only** inside a battery. Nothing else in
the world contains it. If one comes back in a target's answer, the target has
read the battery — and every score in that run is worthless, because the
system under test was holding the answer key.

WHY THIS IS NOT A SCORER
------------------------
A canary hit is not a question the target got wrong. It invalidates the
**run**. Scoring it as one bad answer among ten would let a contaminated
target still certify at 90%, which is precisely backwards: contamination
makes the other nine meaningless too. So detection lives here, the runner
consults it, and §6's target-isolation rule is what it enforces:

    *"the system under test never sees ground truth, scorer code, or
    canaries."*

MINTING
-------
:func:`mint` builds a canary from a caller-supplied token rather than
generating randomness internally. That is deliberate: a battery must hash the
same every time it loads (see ``hashing.py``), and a self-generating canary
would move the hash on every load. The battery author supplies the token
once, at build time, and it is stored.
"""



#: Prefix every canary carries, so a hit is unmistakably a canary and not a
#: coincidence in ordinary prose.
CANARY_PREFIX = "LVL-CANARY"

#: A minted canary. Deliberately ugly: it must never look like something a
#: model would produce on its own.
_CANARY_RE = re.compile(rf"{CANARY_PREFIX}-[A-Z0-9]{{4,}}-[A-Z0-9]{{4,}}")


class CanaryError(ValueError):
    """A canary was malformed or unusable."""


def mint(battery_id: str, token: str) -> str:
    """Build a canary for ``battery_id`` from an author-supplied ``token``.

    Not random. See MINTING above: a canary that regenerates itself would
    move the battery's content hash on every load, and a battery whose
    identity changes when you look at it cannot trigger re-certification
    meaningfully.
    """
    clean_id = re.sub(r"[^A-Za-z0-9]", "", battery_id).upper()
    clean_token = re.sub(r"[^A-Za-z0-9]", "", token).upper()
    if len(clean_id) < 4:
        raise CanaryError(
            f"battery id {battery_id!r} has too few alphanumeric characters to "
            "mint a distinctive canary"
        )
    if len(clean_token) < 4:
        raise CanaryError(
            f"token {token!r} is too short; a canary that could plausibly "
            "appear by chance proves nothing when it appears"
        )
    return f"{CANARY_PREFIX}-{clean_id[:8]}-{clean_token[:12]}"


def is_wellformed(candidate: str) -> bool:
    """Whether ``candidate`` looks like a minted canary."""
    return bool(_CANARY_RE.fullmatch(candidate.strip()))


def find(text: str, canaries: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """Every canary from ``canaries`` that appears in ``text``.

    Case-insensitive: a target that echoes a canary in a different case has
    still seen it, and a comparison that misses that is a comparison that
    can be defeated by ``.lower()``.
    """
    if not text:
        return ()
    haystack = text.casefold()
    return tuple(c for c in canaries if c and c.casefold() in haystack)


def scan_for_any(text: str) -> tuple[str, ...]:
    """Every string in ``text`` that has the *shape* of a canary.

    Catches a leak from a battery this process does not know about -- for
    example a target that was trained on somebody else's battery. A hit here
    is a weaker signal than :func:`find` (it proves a canary leaked, not
    which), and it is still worth having: the alternative is only ever
    finding contamination you already suspected.
    """
    return tuple(dict.fromkeys(_CANARY_RE.findall(text or "")))


def contamination_note(hits: tuple[str, ...]) -> str:
    """The sentence that goes on the run when a canary comes back."""
    return (
        f"{len(hits)} canary string(s) appeared in the target's output. The "
        "target has seen this battery, so every score in this run is void -- "
        "not just the questions that leaked. Re-mint the battery before "
        "running it against this target again."
    )

# ---------------------------------------------------------------------------
# Store adapter
# ---------------------------------------------------------------------------
from app.core.universal_base import UniversalBlock


def _envelope(status, result=None, error=None, detail=None):
    return {
        "block_id": "level_certifier",
        "status": status,
        "result": result,
        "error": error,
        "detail": detail,
    }


class LevelCertifierBlock(UniversalBlock):
    """The Level's certification battery, ported as a single Store block."""

    name = "level_certifier"
    version = "1.0.0"
    description = (
        "real (clone of <private-repo> level/certify/gates.py + level/grader/"
        "independence.py + level/battery/canary.py + level/core/taxonomy.py): "
        "fraction-exact certification gates with CERTIFIED/PROVISIONAL/"
        "NOT_CERTIFIED/VOID tiers and recorded waivers (never floats, never "
        "rounded), a grader-independence check that REFUSES a run where "
        "grader identity == target fingerprint, content-stable canary "
        "minting/detection (a canary hit voids the run), and the 11-class "
        "failure taxonomy. Scorer implementations and the harness runner "
        "are not ported; the gate action takes explicit counts."
    )
    layer = 3
    tags = ["evaluation", "certification", "grading", "gates", "taxonomy", "the-level"]
    requires = []

    default_config = {}

    ui_schema = {
        "input": {
            "type": "json",
            "placeholder": '{"action": "gate", "counted_pass": 19, "counted_total": 20, "trap_pass": 0, "trap_total": 0, "sev1_count": 0, "unscored": 0}',
            "multiline": True,
        },
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "result", "type": "json", "label": "Result"}]},
    }

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "")).lower()
        try:
            if action == "gate":
                return self._gate(payload)
            if action == "independence":
                return self._independence(payload)
            if action == "mint_canary":
                return self._mint(payload)
            if action == "scan_canary":
                return self._scan(payload)
            if action == "taxonomy":
                return _envelope("ok", self._taxonomy())
            return _envelope(
                "error", error=f"unknown action: {action or '(none)'}",
                detail={"known": ["gate", "independence", "mint_canary", "scan_canary", "taxonomy"]},
            )
        except _CertifierRefusal as exc:
            return _envelope("refused", error=str(exc))
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=f"{type(exc).__name__}: {exc}")

    # -- gate -------------------------------------------------------------
    def _gate(self, payload):
        if payload.get("counted_total") is None:
            raise _CertifierRefusal(
                "gate math needs counted_total - certifying nothing is not a "
                "verdict, it is an absence of one"
            )
        config_payload = payload.get("config") or {}
        config = GateConfig.from_dict(config_payload) if config_payload else GateConfig()
        gate = config.evaluate(
            counted_pass=int(payload.get("counted_pass") or 0),
            counted_total=int(payload["counted_total"]),
            trap_pass=int(payload.get("trap_pass") or 0),
            trap_total=int(payload.get("trap_total") or 0),
            sev1_count=int(payload.get("sev1_count") or 0),
            unscored=int(payload.get("unscored") or 0),
            contaminated=bool(payload.get("contaminated")),
        )
        # The donor certifier's contract: the certifier's job is to reach a
        # verdict, and NOT_CERTIFIED (or VOID) is a verdict reached
        # successfully. The tier itself is the loud part.
        return _envelope("ok", {"gate": gate.to_dict(), "config": config.to_dict()})

    # -- independence -----------------------------------------------------
    def _independence(self, payload):
        grader = payload.get("grader") or {}
        target = payload.get("target") or {}
        try:
            kind = GraderKind(str(grader.get("kind") or "deterministic"))
            grader_identity = GraderIdentity(
                kind=kind, identity=str(grader.get("identity") or "")
            )
            fingerprint = TargetFingerprint(
                provider=str(target.get("provider") or ""),
                model=str(target.get("model") or ""),
                version=str(target.get("version") or ""),
                captured_at=str(target.get("captured_at") or ""),
            )
        except ValueError as exc:
            raise _CertifierRefusal(str(exc)) from exc
        reason = refusal_reason(grader_identity, fingerprint)
        if reason:
            return _envelope("refused", error=reason, result={"refusal_reason": reason})
        return _envelope(
            "ok",
            {
                "grader": grader_identity.to_dict(),
                "target": fingerprint.to_dict(),
                "independent": True,
            },
        )

    # -- canary -----------------------------------------------------------
    def _mint(self, payload):
        battery_id = str(payload.get("battery_id") or "")
        token = str(payload.get("token") or "")
        try:
            return _envelope("ok", {"canary": mint(battery_id, token)})
        except CanaryError as exc:
            raise _CertifierRefusal(str(exc)) from exc

    def _scan(self, payload):
        text = str(payload.get("text") or "")
        canaries = [str(c) for c in (payload.get("canaries") or [])]
        hits = find(text, canaries)
        shaped = scan_for_any(text)
        contaminated = bool(hits or shaped)
        result = {
            "hits": list(hits),
            "shaped": list(shaped),
            "contaminated": contaminated,
        }
        if contaminated:
            result["note"] = contamination_note(tuple(hits) + tuple(shaped))
        return _envelope("ok", result)

    # -- taxonomy ---------------------------------------------------------
    @staticmethod
    def _taxonomy():
        return {
            "classes": [c.value for c in FailureClass],
            "severities": {c.value: DEFAULT_SEVERITY[c].value for c in FailureClass},
            "silent_classes": sorted(c.value for c in SILENT_CLASSES),
        }


class _CertifierRefusal(Exception):
    """Internal: input broke a certification contract; surface as refused."""
