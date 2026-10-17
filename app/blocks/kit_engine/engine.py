"""The shared evaluator: five hooks, a hard budget, fail-closed loading.

    question
       ├─ H0  PRE-RETRIEVAL ... scope       refuse without searching
    retrieval
       ├─ H1  RANKING ......... authority   lift the governing class
    tool calls
       ├─ H2  TOOL-TIME ....... unit_discipline · band
    answer draft
       ├─ H3  ANSWER-TIME ..... grounding · qualifier · provenance ·
       │                        currency · derivation · unit_discipline
    deliverable
       └─ H4  EXPORT-TIME ..... re-run H3 on the file before it leaves

Two hooks for unit_discipline, not one, is the load-bearing decision: H2 alone
misses figures the model states without a tool, and H3 alone lets corrupted
values reach exports and source panels before anyone checks. H4 exists for the
same reason one layer further out.

**Budget, non-negotiable.** O(figures × applicable invariants), a hard cap, no
materialised closures, and a check that SKIPS AND LOGS when exceeded. An
unbounded set in exactly this position consumed 2 GB and killed a live instance
twice in one day. A skipped check is not a pass, and ``Outcome.incomplete``
says so, so a host cannot present it as one.

**Fail closed** means one specific thing, and it is the opposite of what a
careless loader does: a kit that does not parse is DISABLED, and a disabled kit
**refuses every statement**. It never loads with zero invariants and waves
everything through — that is a kit with a typo becoming a kit with no gates.
Each kit also has a kill switch (``CEREBRUM_KIT_<NAME>=off``), so a bad kit is
one restart from off rather than one deploy.
"""
from __future__ import annotations

import logging
import os
import pathlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import yaml

from app.blocks.kit_engine.figure import Figure, Finding, Outcome, verdict_for
from app.blocks.kit_engine.invariants import (
    H0_PRE_RETRIEVAL,
    H1_RANKING,
    H2_TOOL_TIME,
    H3_ANSWER_TIME,
    H4_EXPORT_TIME,
    Invariant,
    InvariantError,
    eval_authority,
    eval_band,
    eval_currency,
    eval_derivation,
    eval_grounding,
    eval_provenance,
    eval_qualifier,
    eval_scope,
    eval_unit_discipline,
    parse_invariant,
)
from app.blocks.kit_engine.interview import (
    DesignBasis,
    Interview,
    InterviewError,
    load_design_basis,
    load_interview,
)
from app.blocks.kit_engine.manifest import Manifest, ManifestError, parse_manifest

logger = logging.getLogger(__name__)

#: Hard cap on figure × invariant evaluations per hook call.
DEFAULT_BUDGET = 2000

MANIFEST_FILE = "manifest.yaml"
INVARIANTS_FILE = "invariants.yaml"


class KitLoadError(ValueError):
    """The kit did not load. It is disabled, and a disabled kit refuses."""


def kill_switch_off(kit_name: str, env: Optional[Dict[str, str]] = None) -> bool:
    """``CEREBRUM_KIT_<NAME>=off`` turns one kit off without a deploy."""
    source = env if env is not None else os.environ
    raw = str(source.get(f"CEREBRUM_KIT_{kit_name.upper()}", "") or "").strip().lower()
    return raw in ("0", "off", "false", "no", "disabled")


@dataclass
class Kit:
    manifest: Manifest
    invariants: List[Invariant]
    path: pathlib.Path
    budget: int = DEFAULT_BUDGET
    #: The domain owner's own question sheet, when one was supplied. None means
    #: no sheet exists for this kit and it still runs on the derived questions --
    #: which is NOT the same as a kit whose interview is complete, and every
    #: caller that reports interview state has to say which it is.
    interview: Optional[Interview] = None
    #: The kit's own figure register, where it has one. Six kits were built with a
    #: design_basis.yaml before the generic figure list existed, and it is the
    #: better artefact: domain figure names, mandatory qualifiers per figure, and
    #: its own declared scope. Where this is present it IS the register.
    design_basis: Optional[DesignBasis] = None

    @property
    def name(self) -> str:
        return self.manifest.kit

    @property
    def unmeasured(self) -> List[str]:
        """Records with no measurement case. Spec §4 says no invariant SHIPS
        without one -- the word is *ships*, and §5 puts the AC tests in the
        kit's own tests/. So this LOADS and the ship gate (certification,
        signing) is what refuses. An invariant you cannot count is an opinion,
        and this is the list of opinions."""
        return [inv.id for inv in self.invariants if not inv.measurement]

    @property
    def ships(self) -> bool:
        return not self.unmeasured

    def at(self, hook: str) -> List[Invariant]:
        # H4 re-runs H3 on the deliverable: same invariants, later material -- AND
        # anything declared export-time in its own right.
        #
        # Mapping H4 to H3 alone made a record that declares `hook: H4` unreachable
        # at EVERY hook: H3 skipped it (its hook is H4) and H4 looked for H3. The
        # Store had one, water_treatment's INV-WT-CURRENCY, and it had never fired.
        # Load-time refuses a record that could never fire, but that check reads the
        # record's own fields and cannot see a hook the router never asks for.
        if hook == H4_EXPORT_TIME:
            return [
                inv for inv in self.invariants
                if H3_ANSWER_TIME in inv.hooks() or H4_EXPORT_TIME in inv.hooks()
            ]
        return [inv for inv in self.invariants if hook in inv.hooks()]

    # -- H0 ---------------------------------------------------------------

    def pre_retrieval(self, question: str) -> Outcome:
        """Runs in the router BEFORE anything is retrieved."""
        finding = eval_scope(self.manifest, question)
        findings = [finding] if finding else []
        return Outcome(verdict_for(findings), findings, H0_PRE_RETRIEVAL, self.name)

    # -- H1 ---------------------------------------------------------------

    def ranking(self, figures: Sequence[Figure]) -> Outcome:
        return self._sweep(H1_RANKING, figures)

    # -- H2 ---------------------------------------------------------------

    def tool_time(self, figures: Sequence[Figure]) -> Outcome:
        return self._sweep(H2_TOOL_TIME, figures)

    # -- H3 / H4 ----------------------------------------------------------

    def answer_time(
        self,
        figures: Sequence[Figure],
        state: Optional[Dict[str, Any]] = None,
        events: Sequence[str] = (),
        now: Optional[float] = None,
    ) -> Outcome:
        return self._sweep(H3_ANSWER_TIME, figures, state, events, now)

    def export_time(
        self,
        figures: Sequence[Figure],
        state: Optional[Dict[str, Any]] = None,
        events: Sequence[str] = (),
        now: Optional[float] = None,
    ) -> Outcome:
        outcome = self._sweep(H4_EXPORT_TIME, figures, state, events, now)
        outcome.hook = H4_EXPORT_TIME
        return outcome

    # -- the sweep --------------------------------------------------------

    def _sweep(
        self,
        hook: str,
        figures: Sequence[Figure],
        state: Optional[Dict[str, Any]] = None,
        events: Sequence[str] = (),
        now: Optional[float] = None,
    ) -> Outcome:
        invariants = self.at(hook)
        findings: List[Finding] = []
        spent = 0
        skipped = 0
        for figure in figures:
            # A qualifier the kit does not declare, or one with the wrong type,
            # is reported before any invariant runs: an invariant reading a
            # field it cannot trust is worse than no invariant.
            for name, value in figure.qualifiers.items():
                spec = self.manifest.qualifier_fields.get(name)
                if spec is None:
                    findings.append(Finding(
                        "SCHEMA", "qualifier", "refuse",
                        f"'{name}' is not a declared qualifier field of kit "
                        f"'{self.name}'", figure.quantity,
                    ))
                    continue
                problem = spec.validate(value)
                if problem:
                    findings.append(Finding(
                        "SCHEMA", "qualifier", "refuse", problem, figure.quantity,
                    ))
            for inv in invariants:
                if spent >= self.budget:
                    skipped += 1
                    continue
                spent += 1
                finding = self._one(inv, figure, figures, state, events, now)
                if finding is not None:
                    findings.append(finding)
        if skipped:
            logger.error(
                "KIT BUDGET EXCEEDED %s at %s: %d checks skipped (cap %d). A skipped "
                "check is not a pass", self.name, hook, skipped, self.budget,
            )
        outcome = Outcome(verdict_for(findings), findings, hook, self.name)
        outcome.incomplete = bool(skipped)
        outcome.skipped = skipped
        return outcome

    def _one(
        self,
        inv: Invariant,
        figure: Figure,
        siblings: Sequence[Figure],
        state: Optional[Dict[str, Any]],
        events: Sequence[str],
        now: Optional[float],
    ) -> Optional[Finding]:
        # One governance gate, here, rather than repeated in nine evaluators --
        # a kind that forgot to check would silently govern every quantity.
        if not inv.governs(figure):
            return None
        if inv.kind == "grounding":
            return eval_grounding(inv, figure, self.manifest)
        if inv.kind == "qualifier":
            return eval_qualifier(inv, figure, self.manifest)
        if inv.kind == "unit_discipline":
            return eval_unit_discipline(inv, figure, self.manifest)
        if inv.kind == "authority":
            return eval_authority(inv, figure, self.manifest)
        if inv.kind == "provenance":
            return eval_provenance(inv, figure, self.manifest)
        if inv.kind == "currency":
            return eval_currency(inv, figure, self.manifest, state, events, now)
        if inv.kind == "derivation":
            return eval_derivation(inv, figure, self.manifest, siblings, state)
        if inv.kind == "band":
            return eval_band(inv, figure, self.manifest)
        return None


@dataclass
class DisabledKit:
    """A kit that did not load, or was killed. It refuses everything, by design."""

    name: str
    path: pathlib.Path
    reason: str

    def pre_retrieval(self, question: str) -> Outcome:
        return self._outcome(H0_PRE_RETRIEVAL)

    def ranking(self, figures: Sequence[Figure]) -> Outcome:
        return self._outcome(H1_RANKING)

    def tool_time(self, figures: Sequence[Figure]) -> Outcome:
        return self._outcome(H2_TOOL_TIME)

    def answer_time(self, figures: Sequence[Figure], state=None, events=(), now=None) -> Outcome:
        return self._outcome(H3_ANSWER_TIME)

    def export_time(self, figures: Sequence[Figure], state=None, events=(), now=None) -> Outcome:
        return self._outcome(H4_EXPORT_TIME)

    def _outcome(self, hook: str) -> Outcome:
        finding = Finding(
            "KIT_DISABLED", "scope", "refuse",
            f"kit '{self.name}' is DISABLED and cannot gate anything: {self.reason}. "
            f"A kit that does not load refuses; it does not pass statements through "
            f"with no invariants",
        )
        return Outcome("refused", [finding], hook, self.name)


def load_kit(directory: pathlib.Path, env: Optional[Dict[str, str]] = None) -> Kit:
    """Load ``<dir>/manifest.yaml`` + ``<dir>/invariants.yaml``.

    Raises KitLoadError. The caller disables the kit — it does not default.
    """
    directory = pathlib.Path(directory)
    manifest_path = directory / MANIFEST_FILE
    invariants_path = directory / INVARIANTS_FILE
    for path in (manifest_path, invariants_path):
        if not path.is_file():
            raise KitLoadError(f"{directory.name}: {path.name} is missing")
    try:
        raw_manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise KitLoadError(f"{manifest_path}: unreadable: {exc}") from exc
    try:
        manifest = parse_manifest(raw_manifest, where=str(manifest_path))
    except ManifestError as exc:
        raise KitLoadError(str(exc)) from exc

    if kill_switch_off(manifest.kit, env):
        raise KitLoadError(
            f"kit '{manifest.kit}' is switched off by CEREBRUM_KIT_"
            f"{manifest.kit.upper()}"
        )

    try:
        raw_invariants = yaml.safe_load(invariants_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise KitLoadError(f"{invariants_path}: unreadable: {exc}") from exc
    records = (raw_invariants or {}).get("invariants") if isinstance(raw_invariants, dict) else raw_invariants
    if not records:
        raise KitLoadError(
            f"{invariants_path}: kit '{manifest.kit}' declares no invariants. A kit "
            f"with no invariants gates nothing; it is disabled rather than trusted"
        )

    classes = manifest.quantity_classes()
    invariants: List[Invariant] = []
    seen = set()
    try:
        for record in records:
            inv = parse_invariant(record, classes, where=str(invariants_path))
            if inv.id in seen:
                raise KitLoadError(f"{invariants_path}: duplicate invariant id {inv.id}")
            seen.add(inv.id)
            for quantity in inv.quantities():
                if (
                    quantity not in ("any",)
                    and not quantity.startswith("any_")
                    and quantity not in manifest.quantities
                ):
                    raise KitLoadError(
                        f"{invariants_path}: {inv.id} applies to quantity '{quantity}', "
                        f"which the manifest does not declare"
                    )
            invariants.append(inv)
    except InvariantError as exc:
        raise KitLoadError(str(exc)) from exc

    # A declared staleness trigger that no `currency` invariant governs can never
    # fire. The manifest says "this event invalidates that figure" and nothing
    # ever checks it — the exact silent no-op every other rejection here exists
    # to prevent, so it is a load failure too.
    governed = {
        quantity
        for inv in invariants
        if inv.kind == "currency"
        for quantity in manifest.quantities
        if inv.governs(Figure(quantity=quantity))
    }
    ungoverned = sorted(set(manifest.staleness_triggers) - governed)
    if ungoverned:
        raise KitLoadError(
            f"{invariants_path}: staleness_triggers declares events for "
            f"{', '.join(ungoverned)}, but no currency invariant governs them — the "
            f"trigger could never fire. Add a currency invariant, or drop the trigger"
        )

    # The interview. A sheet that will not parse DISABLES the kit: falling back
    # to "no questions" would read as an interview with nothing outstanding.
    try:
        interview = load_interview(directory)
    except InterviewError as exc:
        raise KitLoadError(str(exc)) from exc
    if interview is not None and interview.kit != manifest.kit:
        raise KitLoadError(
            f"{directory / 'questions.yaml'}: interview names kit '{interview.kit}' but "
            f"the manifest is '{manifest.kit}' — an interview attached to the wrong kit "
            f"would ask one domain's questions and gate another's figures"
        )

    try:
        design_basis = load_design_basis(directory)
    except InterviewError as exc:
        raise KitLoadError(str(exc)) from exc

    return Kit(manifest=manifest, invariants=invariants, path=directory,
               interview=interview, design_basis=design_basis)


class KitRegistry:
    """Every kit under a root, loaded fail-closed. ``get`` never returns None:
    an absent kit is a refusal too."""

    def __init__(self, root: Optional[pathlib.Path] = None) -> None:
        self.root = pathlib.Path(root) if root else pathlib.Path(__file__).resolve().parents[1]
        self.kits: Dict[str, Kit] = {}
        self.disabled: Dict[str, DisabledKit] = {}

    def load_one(self, directory: pathlib.Path, env: Optional[Dict[str, str]] = None) -> Any:
        directory = pathlib.Path(directory)
        try:
            kit = load_kit(directory, env)
        except KitLoadError as exc:
            name = directory.name
            logger.error("KIT DISABLED %s: %s", name, exc)
            disabled = DisabledKit(name=name, path=directory, reason=str(exc))
            self.disabled[name] = disabled
            return disabled
        self.kits[kit.name] = kit
        return kit

    def discover(self, env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        for manifest in sorted(self.root.glob(f"*/{MANIFEST_FILE}")):
            if (manifest.parent / INVARIANTS_FILE).is_file():
                self.load_one(manifest.parent, env)
        return {**self.kits, **self.disabled}

    def get(self, name: str) -> Any:
        if name in self.kits:
            return self.kits[name]
        if name in self.disabled:
            return self.disabled[name]
        return DisabledKit(
            name=name, path=self.root / name,
            reason="no kit of that name is loaded",
        )
