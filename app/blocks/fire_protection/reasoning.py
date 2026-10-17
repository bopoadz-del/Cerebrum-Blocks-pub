"""Fire protection & firefighting systems — the design-basis loader and the
live-state model.

The invariant pipeline itself has moved to the shared kit_engine evaluator
(``app/blocks/kit_engine``), driven declaratively by ``manifest.yaml`` and
``invariants.yaml`` in this directory. This module keeps only the two pieces
that are NOT part of the reasoning-layer vocabulary:

  FireProtectionBasis  the design-basis interview-gap loader (design_basis.yaml)
  SystemState          the two-source live-state model (impairment log +
                        live system status)

``app.blocks.fire_protection_reasoning`` (the store-facing wrapper) is the
host: it builds ``Figure`` objects from a query/answer/context and drives the
kit through its five hooks.
"""
from __future__ import annotations

import pathlib
import time
from typing import Any, Dict, List, Optional

import yaml

_DESIGN_BASIS_PATH = pathlib.Path(__file__).parent / "design_basis.yaml"

#: Every design-basis figure carries these. A null VALUE is legal — the
#: interview has not run. A missing QUALIFIER is not: half-qualified is how an
#: unclassified density table ends up answering a classified question.
MANDATORY_QUALIFIERS = (
    "value",
    "unit",
    "code_edition",
    "classification_source",
    "design_area_basis",
    "tested_assembly_ref",
    "in_service",
    "impairment_log_ref",
    "source",
    "date",
)

DESIGN_AREA_BASES = ("most_remote", "most_demanding")

#: Hazard classifications the sheet recognises. The host's own figure
#: extraction validates against this closed list before ever setting the
#: `classification` qualifier — the loader accepts any string (see
#: manifest.yaml's comment on that field), so a closed vocabulary is
#: enforced here, once, rather than invented ahead of the interview.
HAZARD_CLASSIFICATIONS = (
    "light_hazard",
    "ordinary_hazard_1",
    "ordinary_hazard_2",
    "extra_hazard_1",
    "extra_hazard_2",
)


class ManifestError(ValueError):
    """A design-basis figure arrived without its mandatory qualifiers."""


class FireProtectionBasis:
    """The fire protection design basis, loaded from design_basis.yaml.

    The loader is the first gate. It refuses at LOAD time — not at answer
    time — so a half-qualified figure cannot sit in the design basis waiting
    to be quoted. The refusal names the figure and every key it lacks.
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
                    f"design basis figure '{name}' is not a qualified entry; every "
                    f"figure is a mapping carrying {', '.join(MANDATORY_QUALIFIERS)}"
                )
            missing = [key for key in MANDATORY_QUALIFIERS if key not in entry]
            if missing:
                raise ManifestError(
                    f"design basis figure '{name}' is partially qualified — missing "
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


class SystemState:
    """Current fire protection system state. Requires BOTH sources:

    - ``impairment_log``: active isolations, valves closed, components racked
      out — what a drawing or a design record cannot show.
    - ``live_status``: what the system is doing right now — pump running,
      valves in normal position, in_service flag.

    The impairment log is a HARD precondition for any coverage answer: a
    design record showing the system as designed is not proof the system is
    covered right now. If a source is unreachable, that source's state is
    UNKNOWN to the shared evaluator's currency invariants — there is no
    design-basis fallback for live state, ever.
    """

    #: Impairment status goes stale in minutes, not hours — a valve closed
    #: five minutes ago for maintenance is not reflected in a reading from an
    #: hour earlier, and reporting it as current is the failure this gate
    #: exists to stop. Matches manifest.yaml's state_providers max_age.
    MAX_AGE_SECONDS = 900

    def __init__(
        self,
        impairment_log: Optional[Dict[str, Any]],
        live_status: Optional[Dict[str, Any]],
        fetched_at: Optional[float] = None,
    ) -> None:
        self.impairment_log = impairment_log
        self.live_status = live_status
        self.fetched_at = fetched_at if fetched_at is not None else time.time()

    def both_sources_present(self) -> bool:
        return self.impairment_log is not None and self.live_status is not None

    def fresh(self) -> bool:
        return (time.time() - self.fetched_at) <= self.MAX_AGE_SECONDS

    def in_service(self) -> Optional[bool]:
        return (self.live_status or {}).get("in_service")

    def active_impairments(self) -> List[Dict[str, Any]]:
        return list((self.impairment_log or {}).get("active_impairments") or [])
