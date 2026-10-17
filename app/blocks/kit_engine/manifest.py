"""Kit manifest — the vocabulary. Declarative, and the evaluator knows none of it.

Nothing in the evaluator knows what a runway or a slab is. The manifest supplies:

  quantities          what figures this domain talks about, and their legal units
  qualifier_fields    the vocabulary of completeness
  source_classes      the authority ladder: rank, and what each class may NOT prove
  state_providers     what "current" means here
  staleness_triggers  the EVENTS that invalidate a figure, not only elapsed time
  scope_refusals      whole question classes, refused pre-retrieval

Parsing is strict and total. Every rejection below exists because the silent
alternative is a kit that loads with a gate missing and reports green — and a
kit that does not load is DISABLED, which means it refuses, not that it passes.
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

FIELD_TYPES = ("number", "string", "enum", "date", "bool")
PROVIDER_KINDS = ("cycle", "status", "revision")


class ManifestError(ValueError):
    """The manifest is not usable. The kit is disabled; a disabled kit refuses."""


@dataclass(frozen=True)
class FieldSpec:
    name: str
    type: str
    values: Tuple[str, ...] = ()
    pattern: Optional[str] = None

    def validate(self, value: Any) -> Optional[str]:
        """None when acceptable, else why not. Null is always acceptable here:
        a missing qualifier is the `qualifier` kind's business, not the type
        checker's."""
        if value is None:
            return None
        if self.type == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return f"{self.name} must be a number, got {type(value).__name__}"
            return None
        if self.type == "bool":
            if not isinstance(value, bool):
                return f"{self.name} must be true or false, got {value!r}"
            return None
        if self.type == "enum":
            if value not in self.values:
                return (
                    f"{self.name} must be one of {', '.join(map(str, self.values))}, "
                    f"got {value!r}"
                )
            return None
        if self.type == "date":
            if isinstance(value, (_dt.date, _dt.datetime)):
                return None
            try:
                _dt.date.fromisoformat(str(value))
            except ValueError:
                return f"{self.name} must be an ISO date, got {value!r}"
            return None
        text = str(value)
        if self.pattern and not re.fullmatch(self.pattern, text):
            return f"{self.name} must match {self.pattern}, got {value!r}"
        return None


@dataclass(frozen=True)
class QuantitySpec:
    name: str
    units: Tuple[str, ...] = ()
    aliases: Tuple[str, ...] = ()
    #: Classes this quantity belongs to, so an invariant can say `any_length`
    #: without saying "everything".
    classes: Tuple[str, ...] = ()


@dataclass(frozen=True)
class SourceClass:
    """One rung of the authority ladder.

    ``rank`` is 1 = most governing. ``reject_as_proof`` names the classes this
    class may NOT stand in for: a site-office mobilisation note does not answer
    a specification question, and that defect shipped live.
    """

    name: str
    rank: int
    name_patterns: Tuple[str, ...] = ()
    reject_as_proof: Tuple[str, ...] = ()

    def matches(self, text: str) -> bool:
        return any(re.search(p, text or "", re.IGNORECASE) for p in self.name_patterns)


@dataclass(frozen=True)
class StateProvider:
    name: str
    kind: str
    #: Seconds, or an EVENT name. "current" in a plant is usually an event
    #: ("any valve operation"), not a clock.
    max_age: Optional[Any] = None

    @property
    def max_age_seconds(self) -> Optional[float]:
        """Seconds, or None when ``max_age`` names an EVENT rather than a duration.

        Written out rather than ``try: float(...) except: return None``. None here
        carries a meaning -- "this window is an event, ask ``max_age_event``" -- and
        a swallowed exception makes an unparseable value indistinguishable from a
        deliberate event name. The repo's own CI guard forbids the silent form, and
        it is right to: the two cases need telling apart.
        """
        value = self.max_age
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        # A duration written as a YAML string ("3600") is still a duration.
        text = str(value).strip()
        if re.fullmatch(r"-?\d+(?:\.\d+)?", text):
            return float(text)
        return None

    @property
    def max_age_event(self) -> Optional[str]:
        return None if self.max_age_seconds is not None else (
            str(self.max_age) if self.max_age else None
        )


@dataclass(frozen=True)
class ScopeRefusal:
    pattern: str
    authority: str
    label: str = "operational authority"

    def matches(self, question: str) -> bool:
        return bool(re.search(self.pattern, question or "", re.IGNORECASE))


@dataclass
class Manifest:
    kit: str
    version: int
    quantities: Dict[str, QuantitySpec] = field(default_factory=dict)
    qualifier_fields: Dict[str, FieldSpec] = field(default_factory=dict)
    source_classes: Dict[str, SourceClass] = field(default_factory=dict)
    state_providers: Dict[str, StateProvider] = field(default_factory=dict)
    staleness_triggers: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    scope_refusals: List[ScopeRefusal] = field(default_factory=list)
    interview_status: str = "not run"
    figures: Dict[str, Any] = field(default_factory=dict)

    def quantity_classes(self) -> Dict[str, Tuple[str, ...]]:
        out: Dict[str, List[str]] = {}
        for name, spec in self.quantities.items():
            for cls in spec.classes:
                out.setdefault(cls, []).append(name)
        return {cls: tuple(names) for cls, names in out.items()}

    def unfilled(self) -> List[str]:
        return sorted(
            str(name) for name, entry in self.figures.items()
            if not isinstance(entry, dict) or entry.get("value") is None
        )


def _tuple(raw: Any) -> Tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        return (raw,)
    return tuple(str(item) for item in raw)


def parse_manifest(raw: Any, where: str = "manifest") -> Manifest:
    if not isinstance(raw, dict):
        raise ManifestError(f"{where}: manifest is not a mapping")
    kit = str(raw.get("kit") or "").strip()
    if not kit:
        raise ManifestError(f"{where}: manifest declares no kit name")

    quantities: Dict[str, QuantitySpec] = {}
    for name, decl in (raw.get("quantities") or {}).items():
        decl = decl or {}
        if not isinstance(decl, dict):
            raise ManifestError(f"{where}: quantity '{name}' must be a mapping")
        classes = _tuple(decl.get("classes"))
        for cls in classes:
            if not cls.startswith("any_"):
                raise ManifestError(
                    f"{where}: quantity class '{cls}' must be named any_*, so a reader "
                    f"can tell a class from a quantity"
                )
        quantities[str(name)] = QuantitySpec(
            name=str(name),
            units=_tuple(decl.get("units")),
            aliases=_tuple(decl.get("aliases")),
            classes=classes,
        )
    if not quantities:
        raise ManifestError(
            f"{where}: kit '{kit}' declares no quantities. An invariant that applies "
            f"to no quantity governs nothing"
        )

    qualifier_fields: Dict[str, FieldSpec] = {}
    for name, decl in (raw.get("qualifier_fields") or {}).items():
        if not isinstance(decl, dict):
            raise ManifestError(f"{where}: qualifier field '{name}' must be a mapping")
        kind = str(decl.get("type") or "").strip()
        if kind not in FIELD_TYPES:
            raise ManifestError(
                f"{where}: field '{name}' has type {kind!r}; expected one of "
                f"{', '.join(FIELD_TYPES)}"
            )
        values = _tuple(decl.get("values"))
        if kind == "enum" and not values:
            raise ManifestError(f"{where}: enum field '{name}' declares no values")
        pattern = decl.get("pattern")
        if pattern is not None:
            try:
                re.compile(str(pattern))
            except re.error as exc:
                raise ManifestError(f"{where}: field '{name}' pattern unusable: {exc}") from exc
        qualifier_fields[str(name)] = FieldSpec(
            name=str(name), type=kind, values=values,
            pattern=str(pattern) if pattern is not None else None,
        )

    source_classes: Dict[str, SourceClass] = {}
    for name, decl in (raw.get("source_classes") or {}).items():
        decl = decl or {}
        if not isinstance(decl, dict):
            raise ManifestError(f"{where}: source class '{name}' must be a mapping")
        if decl.get("rank") is None:
            raise ManifestError(
                f"{where}: source class '{name}' declares no rank — an authority "
                f"ladder with an unranked rung cannot order anything"
            )
        source_classes[str(name)] = SourceClass(
            name=str(name),
            rank=int(decl["rank"]),
            name_patterns=_tuple(decl.get("name_patterns")),
            reject_as_proof=_tuple(decl.get("reject_as_proof")),
        )
    for name, spec in source_classes.items():
        for rejected in spec.reject_as_proof:
            if rejected not in source_classes:
                raise ManifestError(
                    f"{where}: source class '{name}' rejects '{rejected}' as proof, but "
                    f"'{rejected}' is not a declared class — the rule could never fire"
                )

    state_providers: Dict[str, StateProvider] = {}
    for name, decl in (raw.get("state_providers") or {}).items():
        decl = decl or {}
        if not isinstance(decl, dict):
            raise ManifestError(f"{where}: state provider '{name}' must be a mapping")
        kind = str(decl.get("kind") or "").strip()
        if kind not in PROVIDER_KINDS:
            raise ManifestError(
                f"{where}: state provider '{name}' has kind {kind!r}; expected one of "
                f"{', '.join(PROVIDER_KINDS)}"
            )
        state_providers[str(name)] = StateProvider(
            name=str(name), kind=kind, max_age=decl.get("max_age"),
        )

    staleness: Dict[str, Tuple[str, ...]] = {}
    for quantity, events in (raw.get("staleness_triggers") or {}).items():
        triggers = _tuple(events)
        if not triggers:
            raise ManifestError(
                f"{where}: staleness_triggers['{quantity}'] is empty — declare the "
                f"events that invalidate it, or leave it out"
            )
        if str(quantity) not in quantities:
            raise ManifestError(
                f"{where}: staleness_triggers names quantity '{quantity}', which the "
                f"kit does not declare"
            )
        staleness[str(quantity)] = triggers

    refusals: List[ScopeRefusal] = []
    for entry in (raw.get("scope_refusals") or []):
        if not isinstance(entry, dict) or not entry.get("pattern"):
            raise ManifestError(f"{where}: each scope refusal needs a 'pattern'")
        if not entry.get("authority"):
            raise ManifestError(
                f"{where}: scope refusal {entry.get('pattern')!r} names no authority — "
                f"a refusal that does not say who decides is a dead end"
            )
        try:
            re.compile(str(entry["pattern"]), re.IGNORECASE)
        except re.error as exc:
            raise ManifestError(f"{where}: unusable scope pattern: {exc}") from exc
        refusals.append(ScopeRefusal(
            pattern=str(entry["pattern"]),
            authority=str(entry["authority"]),
            label=str(entry.get("label") or "operational authority"),
        ))

    return Manifest(
        kit=kit,
        version=int(raw.get("version") or 1),
        quantities=quantities,
        qualifier_fields=qualifier_fields,
        source_classes=source_classes,
        state_providers=state_providers,
        staleness_triggers=staleness,
        scope_refusals=refusals,
        interview_status=str(raw.get("interview_status") or "not run"),
        figures=dict(raw.get("figures") or {}),
    )
