"""Store-facing host for a declarative reasoning kit.

One base class. A kit's block is a subclass that names its kit and nothing else,
which is the whole point of the shared evaluator: the domain lives in
``manifest.yaml`` + ``invariants.yaml``, never in Python.

The host implements the four functions the portable spec's §3 contract names —
``extract_figures``, ``resolve_source``, ``state``, ``apply`` — in the only way a
block can: the CALLER supplies them. A block cannot read a platform's corpus or
its SCADA, so the caller passes figures, source classes and state records in,
and the block returns the outcome for the caller to apply. Nothing here guesses:
no qualifier, claim class, source class or live state is inferred from prose,
because inferring them is the defect this layer exists to catch.

Every hook is exposed. A host that calls only ``answer_time`` silently gets no
``authority`` (H1) or ``band`` (H2) coverage, so ``process`` runs the whole
routing map by default and says which hooks it ran.

Fail closed: an unloadable kit is DISABLED and refuses every statement. It never
degrades to "no invariants".
"""
from __future__ import annotations

import pathlib
from typing import Any, Dict, List, Optional, Sequence

from app.blocks.kit_engine import Figure, Outcome
from app.blocks.kit_engine.engine import DisabledKit, KitLoadError, load_kit
from app.core.universal_base import UniversalBlock

KITS_ROOT = pathlib.Path(__file__).resolve().parent

#: The routing map, in order. `process` runs all of them unless the caller
#: names a subset, because a partial sweep is a silent coverage gap.
ALL_HOOKS = ("H0", "H1", "H2", "H3", "H4")


def load(kit_name: str):
    """The kit, or its disabled stand-in. Never None: absent is refusal too."""
    try:
        return load_kit(KITS_ROOT / kit_name)
    except KitLoadError as exc:
        return DisabledKit(name=kit_name, path=KITS_ROOT / kit_name, reason=str(exc))


def figures_from(raw: Any) -> List[Figure]:
    """Build Figures from what the caller passed. Unknown keys are refused by
    the engine's schema check, not silently dropped."""
    if raw is None:
        return []
    if isinstance(raw, dict):
        raw = [raw]
    out: List[Figure] = []
    for item in raw:
        if isinstance(item, Figure):
            out.append(item)
            continue
        if not isinstance(item, dict):
            raise ValueError("each figure must be a mapping or a Figure")
        out.append(Figure(
            quantity=str(item.get("quantity") or ""),
            value=item.get("value"),
            unit=item.get("unit"),
            origin=str(item.get("origin") or "model"),
            source_id=item.get("source_id"),
            source_class=item.get("source_class"),
            revision=item.get("revision"),
            effective_date=item.get("effective_date"),
            qualifiers=dict(item.get("qualifiers") or {}),
            span=item.get("span"),
            text=str(item.get("text") or ""),
            asked_about=dict(item.get("asked_about") or {}),
            claim_class=item.get("claim_class"),
            derivations=list(item.get("derivations") or []),
            conditions=list(item.get("conditions") or []),
            steps=list(item.get("steps") or []),
            bounds=dict(item.get("bounds") or {}),
        ))
    return out


def _merge(outcomes: Sequence[Outcome], kit_name: str) -> Dict[str, Any]:
    """One verdict from the whole sweep. A refusal anywhere refuses the answer:
    block means the WHOLE answer, not the offending clause."""
    findings = [f for o in outcomes for f in o.findings]
    verdict = "pass"
    if any(f.severity == "refuse" for f in findings):
        verdict = "refused"
    elif any(f.severity == "flag" for f in findings):
        verdict = "flagged"
    elif findings:
        verdict = "annotated"
    return {
        "verdict": verdict,
        "kit": kit_name,
        "hooks_run": [o.hook for o in outcomes],
        "findings": [f.as_dict() for f in findings],
        "blocked_reason": "; ".join(f.message for f in findings if f.severity == "refuse"),
        # A skipped check is NOT a pass, and the caller must not present it as one.
        "incomplete": any(o.incomplete for o in outcomes),
        "skipped_checks": sum(o.skipped for o in outcomes),
    }


class ReasoningKitBlock(UniversalBlock):
    """Base for every domain reasoning kit. Subclasses set ``kit_name``."""

    kit_name: str = ""
    layer = 3
    version = "1.0.0"
    requires: list = []

    def envelope(self, status, result=None, error=None, detail=None) -> Dict[str, Any]:
        return {
            "block_id": self.name,
            "status": status,
            "result": result,
            "error": error,
            "detail": detail,
        }

    async def run_kit(self, input_data: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        """The whole routing map for this kit. Each kit's block defines its own
        ``process`` and calls this, so certification bar 3 mutates that kit's own
        file rather than one shared method standing in for seventeen."""
        try:
            kit = load(self.kit_name)
            question = str(input_data.get("question") or input_data.get("query") or "").strip()

            # H0 first, and on its own: a scope refusal must be returned BEFORE
            # anything is retrieved, so a caller that only asks H0 gets the
            # refusal without ever touching a corpus.
            hooks = [str(h).upper() for h in (input_data.get("hooks") or ALL_HOOKS)]
            outcomes: List[Outcome] = []
            if "H0" in hooks and question:
                first = kit.pre_retrieval(question)
                outcomes.append(first)
                if first.verdict == "refused":
                    result = _merge(outcomes, kit.name)
                    result["retrieval_permitted"] = False
                    return self.envelope("success", result=self._with_gaps(kit, result))

            try:
                figures = figures_from(input_data.get("figures"))
            except ValueError as exc:
                return self.envelope("refused", error=str(exc))
            if not figures:
                if not question:
                    return self.envelope(
                        "refused",
                        error="a question (for H0) or at least one figure is required",
                    )
                result = _merge(outcomes, kit.name)
                result["retrieval_permitted"] = True
                return self.envelope("success", result=self._with_gaps(kit, result))

            state = input_data.get("state")
            events = list(input_data.get("events") or [])
            if "H1" in hooks:
                outcomes.append(kit.ranking(figures))
            if "H2" in hooks:
                outcomes.append(kit.tool_time(figures))
            if "H3" in hooks:
                outcomes.append(kit.answer_time(figures, state, events))
            if "H4" in hooks:
                outcomes.append(kit.export_time(figures, state, events))

            result = _merge(outcomes, kit.name)
            result["retrieval_permitted"] = True
            return self.envelope("success", result=self._with_gaps(kit, result))
        except Exception as exc:  # noqa: BLE001 — a gate that dies silently is worse
            return self.envelope("error", error=f"{type(exc).__name__}: {exc}")

    def _with_gaps(self, kit, result: Dict[str, Any]) -> Dict[str, Any]:
        """The interview state travels with every answer: a caller must be able
        to see that no value has been filled, and which records are unmeasured."""
        manifest = getattr(kit, "manifest", None)
        result["interview_status"] = getattr(manifest, "interview_status", "unknown")
        result["unfilled_figures"] = list(manifest.unfilled()) if manifest else []
        result["unmeasured_invariants"] = list(getattr(kit, "unmeasured", []))
        result["ships"] = bool(getattr(kit, "ships", False))
        result["kit_disabled"] = isinstance(kit, DisabledKit)
        result["interview"] = self._interview_state(kit)
        return result

    def _interview_state(self, kit) -> Dict[str, Any]:
        """What the domain owner's sheet still wants answered.

        The caller passes no answers here — a Store block cannot read a
        platform's answer store and must never hold one. So this reports the
        interview as it stands in the kit: every gating question outstanding.
        The platform's own kernel overlays the answers it holds.

        ``questions_source`` is the point of this method. A kit with no sheet and
        a kit whose sheet is fully answered both have nothing outstanding here,
        and reporting them the same way would say the loudest possible untruth:
        that a domain nobody has interviewed is ready.
        """
        interview = getattr(kit, "interview", None)
        basis = getattr(kit, "design_basis", None)
        manifest = getattr(kit, "manifest", None)

        state: Dict[str, Any] = {
            "sheet_supplied": interview is not None,
            "design_basis_supplied": basis is not None,
        }

        # The kit's OWN figure register, where it has one. This comes first
        # because it is the only source that can already hold answers: one of the
        # six is filled in. Reporting such a kit as un-interviewed, which an
        # earlier version did, calls an answered domain an empty one.
        if basis is not None:
            state["design_basis"] = basis.status()

        if interview is not None:
            state.update(interview.status({}))
            state["title"] = interview.title
            state["next"] = [q.as_dict() for q in interview.outstanding({})[:5]]

        if basis is not None:
            # Top-level, so no caller can read "1 figure open" as "nobody has
            # interviewed this domain". One of the six registers is filled.
            state["interview_ran"] = basis.ran

        if basis is not None and interview is not None:
            # Both, and they answer different questions: the register holds this
            # facility's figures, the sheet asks the organisation's rules.
            state["questions_source"] = "design_basis+owner_sheet"
            state["note"] = (
                f"Two sources, and they are not alternatives. The figure register "
                f"({len(basis.answered)}/{len(basis.figures)} answered) holds the "
                f"figures for {basis.facility or 'this asset'}; the owner's question "
                f"sheet ({len(interview.outstanding({}))} gating questions outstanding) "
                f"asks the organisation's own rules. Both have to be answered."
            )
        elif basis is not None:
            state["questions_source"] = "design_basis"
            state["figures"] = len(basis.figures)
            state["answered"] = len(basis.answered)
            state["outstanding"] = len(basis.open)
            state["ready"] = basis.ran and not basis.open
            if not basis.ran:
                state["note"] = (
                    "This kit's figure register is declared and EMPTY — no interview "
                    "has run, every value is null. Nothing needing one of these "
                    "figures can be answered.")
            else:
                state["note"] = (
                    f"Answered from this kit's own figure register for "
                    f"{basis.facility or 'its declared scope'}: "
                    f"{len(basis.answered)} of {len(basis.figures)} figures. "
                    f"{basis.scope}")
        elif interview is not None:
            state["questions_source"] = "owner_sheet"
        else:
            unfilled = list(getattr(manifest, "unfilled", lambda: [])())
            state.update({
                "questions_source": "derived",
                "note": (
                    "This kit has neither a question sheet nor a figure register. The "
                    "questions it asks are DERIVED from its quantity names, one per "
                    "quantity, and are not the domain owner's own. Nothing is answered."
                ),
                "outstanding": len(unfilled),
                "ready": False,
            })
        return state
