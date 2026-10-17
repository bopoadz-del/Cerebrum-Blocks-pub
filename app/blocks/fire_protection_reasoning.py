"""Fire protection & firefighting systems reasoning gate — store-facing wrapper.

The invariant pipeline has moved to the shared kit_engine evaluator
(``app/blocks/kit_engine``), declared by ``app/blocks/fire_protection/
manifest.yaml`` and ``invariants.yaml``. This module is the HOST the portable
spec describes: it extracts ``Figure`` objects from a query/answer/context,
resolves each figure's evidentiary source class, builds the live-state and
design-basis-revision ``state`` dict, and drives the kit through its hooks.
Nothing here knows the eight invariant kinds' own logic — that lives in
``app.blocks.kit_engine`` and is not touched.

The block id is ``fire_protection_reasoning``, the class carries identity
metadata, and every statement is routed through the kit — there is no bypass.
``async def process()`` and its input/output envelope shape are unchanged
from the hand-written gate this replaces, so the certification entry
(module/class/method) and every caller still hold.

Provenance: structure only. The domain encoding sheet for Fire Protection &
Firefighting Systems defines the invariants; NO INTERVIEW HAS RUN, so every
design_basis.yaml value is null (``app/blocks/fire_protection/KNOWN_GAPS.md``).
This block refuses; it does not supply figures it does not have.
"""
from __future__ import annotations

import pathlib
import re
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.blocks.fire_protection.reasoning import FireProtectionBasis, SystemState
from app.blocks.kit_engine import Figure, KitRegistry
from app.blocks.kit_engine.figure import Outcome, verdict_for
from app.blocks.kit_engine.invariants import H3_ANSWER_TIME
from app.core.universal_base import UniversalBlock

_KIT_DIR = pathlib.Path(__file__).parent / "fire_protection"
_REGISTRY = KitRegistry(_KIT_DIR.parent)
_KIT = _REGISTRY.load_one(_KIT_DIR)


def _envelope(status, result=None, error=None, detail=None):
    return {
        "block_id": "fire_protection_reasoning",
        "status": status,
        "result": result,
        "error": error,
        "detail": detail,
    }


# --------------------------------------------------------------------------
# host-side figure extraction — the four functions the portable spec asks a
# host to implement (extract_figures / resolve_source / state / apply),
# folded into this module rather than named separately, since fire_protection
# has exactly one caller (process()) and one kit.
# --------------------------------------------------------------------------

#: Which quantity a query+answer statement is about. Unchanged from the
#: hand-written gate's own trigger words — these decide WHICH figure gets
#: built, not whether it passes; every invariant that used to be a bespoke
#: check now lives in invariants.yaml and runs on the Figure this builds.
CLASSIFICATION_WORDS = re.compile(
    r"hazard\s+class(?:ification)?|light\s+hazard|ordinary\s+hazard|"
    r"extra\s+hazard|classified\s+as|classification\s+is",
    re.IGNORECASE)
DENSITY_WORDS = re.compile(
    r"design\s+density|discharge\s+density|density\s+(?:is|of|at|for)|"
    r"gpm\s*/\s*ft|mm\s*/\s*min|design\s+area\s+(?:is|of)",
    re.IGNORECASE)
DESIGN_BASIS_WORDS = re.compile(r"design\s+basis", re.IGNORECASE)
COVERAGE_WORDS = re.compile(
    r"adequately\s+protected|is\s+(?:it|this|the\s+\w+)\s+covered|"
    r"coverage\s+(?:is|of)|fully\s+covered|protected\s+(?:by|against)|"
    r"is\s+the\s+system\s+available",
    re.IGNORECASE)
RATING_WORDS = re.compile(
    r"fire\s+rating|fire[-\s]?rated|hour\s+rating|\d\s*-?\s*hour\s+rated|"
    r"fire\s+resistance\s+rating|rated\s+(?:wall|floor|door|assembly|"
    r"partition|enclosure)",
    re.IGNORECASE)
SUPPLY_WORDS = re.compile(
    r"water\s+supply|available\s+(?:flow|pressure)|residual\s+pressure|"
    r"supply\s+(?:is|of)\s+\d|flow\s+test\s+result",
    re.IGNORECASE)

#: Qualifier-value extraction. A structured input_data field always wins;
#: these regexes are the fallback the answer's own prose gets checked
#: against — exactly what the hand-written gate did with
#: ``x or PATTERN.search(answer)``.
_DESIGN_AREA_MENTION = re.compile(r"most[-\s]?remote|most[-\s]?demanding", re.IGNORECASE)
_ANALYSED_MENTION = re.compile(r"analys(?:ed|is|ing)|actually\s+analy", re.IGNORECASE)
ATTRIBUTION_MENTION = re.compile(
    r"engineer\s+of\s+record|per\s+the\s+engineer|named\s+engineer|"
    r"approved\s+(?:fire\s+protection\s+)?(?:report|document|drawing|design)|"
    r"determin(?:ed|ation)\s+by\s+(?:the\s+)?engineer|\bP\.?E\.?\b",
    re.IGNORECASE)
ASSEMBLY_MENTION = re.compile(
    r"assembly\s*(?:no\.?|number|ref(?:erence)?)|UL\s*[A-Z]?\s*\d+|"
    r"listing\s+design|tested\s+assembly|penetration\s+detail",
    re.IGNORECASE)
_CODE_EDITION_MENTION = re.compile(
    r"NFPA\s*\d+[,\s]*\(?\d{4}\)?|IBC\s*\d{4}|\d{4}\s+edition", re.IGNORECASE)
_CODE_EDITION_TOKEN = re.compile(
    r"NFPA\s*\d+[,\s]*\(?(\d{4})\)?|(\d{4})\s+edition", re.IGNORECASE)
_CARRY_VERB = re.compile(
    r"\bsame\b|\bapply\b|\bapplies\b|\bcarry\b|\breuse\b|\bas\s+well\b|"
    r"\buse\s+the\b|\bequivalent\b|\btransfer\b|\bunchanged\b",
    re.IGNORECASE)
_SIMILAR_BUILDING = re.compile(
    r"(?:similar|sister|comparable|identical)\s+building", re.IGNORECASE)

#: Numeric value extraction, for band and derivation (self-contradiction).
_DENSITY_VALUE = re.compile(r"(\d+(?:\.\d+)?)\s*gpm\s*/\s*ft2?", re.IGNORECASE)
_RATING_VALUE = re.compile(r"(\d+(?:\.\d+)?)\s*-?\s*hour", re.IGNORECASE)

#: Ordered specific-before-generic, so "extra hazard" alone still resolves to
#: a group rather than being left unclassified.
_CLASSIFICATION_TOKENS: Tuple[Tuple[str, "re.Pattern"], ...] = (
    ("extra_hazard_2", re.compile(r"extra\s+hazard\s*(?:group\s*)?(?:2|ii)\b", re.IGNORECASE)),
    ("extra_hazard_1", re.compile(r"extra\s+hazard\s*(?:group\s*)?(?:1|i)\b", re.IGNORECASE)),
    ("extra_hazard_1", re.compile(r"\bextra\s+hazard\b", re.IGNORECASE)),
    ("ordinary_hazard_2", re.compile(r"ordinary\s+hazard\s*(?:group\s*)?(?:2|ii)\b", re.IGNORECASE)),
    ("ordinary_hazard_1", re.compile(r"ordinary\s+hazard\s*(?:group\s*)?(?:1|i)\b", re.IGNORECASE)),
    ("ordinary_hazard_1", re.compile(r"\bordinary\s+hazard\b", re.IGNORECASE)),
    ("light_hazard", re.compile(r"light\s+hazard", re.IGNORECASE)),
)

def _matches_any(name: str, pool: Sequence[str]) -> bool:
    manifest = getattr(_KIT, "manifest", None)
    spec = manifest.source_classes.get(name) if manifest is not None else None
    return bool(spec is not None and any(spec.matches(item) for item in pool))


def code_editions_mentioned(text: str) -> List[str]:
    """Distinct code-edition years named in *text*, in the order they appear."""
    found: List[str] = []
    for match in _CODE_EDITION_TOKEN.finditer(text or ""):
        year = match.group(1) or match.group(2)
        if year and year not in found:
            found.append(year)
    return found


def _classification_token(text: str) -> Optional[str]:
    for token, pattern in _CLASSIFICATION_TOKENS:
        if pattern.search(text or ""):
            return token
    return None


#: Per-quantity source_class resolution, mirroring the REJECT_AS_PROOF ladder
#: in manifest.yaml. The GOVERNING class is resolved from the same signal
#: that already satisfies that quantity's qualifier invariant — an
#: attribution mention IS the engineer's determination, a tested-assembly
#: mention IS the listing, a live SystemState IS the live-state record — so a
#: fully-qualified answer never fails authority purely for want of a second,
#: independent citation the qualifier check did not also require. The weak
#: (REJECT_AS_PROOF) classes are checked FIRST and always come from an actual
#: textual or evidence-list signal, never invented.

def _classification_source_class(combined: str, evidence: Sequence[str], attribution: Optional[str]) -> Optional[str]:
    pool = list(evidence) + [combined]
    for weak in ("occupancy_inference", "visual_inspection"):
        if _matches_any(weak, pool):
            return weak
    return "engineer_determination" if attribution else None


def _density_source_class(combined: str, evidence: Sequence[str], classification: Optional[str]) -> Optional[str]:
    pool = list(evidence) + [combined]
    if _matches_any("unclassified_table", pool):
        return "unclassified_table"
    if classification:
        return "classified_density_table"
    return "classified_density_table" if _matches_any("classified_density_table", pool) else None


def _rating_source_class(combined: str, evidence: Sequence[str], assembly: Optional[str]) -> Optional[str]:
    pool = list(evidence) + [combined]
    if _matches_any("product_data_sheet", pool):
        return "product_data_sheet"
    return "tested_assembly_listing" if assembly else None


def _supply_source_class(combined: str, evidence: Sequence[str], flow_test: Optional[Dict[str, Any]]) -> Optional[str]:
    pool = list(evidence) + [combined]
    for weak in ("nameplate_rating", "pump_curve_estimate", "design_flow_assumption"):
        if _matches_any(weak, pool):
            return weak
    if flow_test is not None:
        return "current_flow_test"
    return "current_flow_test" if _matches_any("current_flow_test", pool) else None


def _coverage_source_class(
    combined: str, evidence: Sequence[str], system_state: Optional[SystemState]
) -> Optional[str]:
    pool = list(evidence) + [combined]
    if _matches_any("design_drawing_evidence", pool):
        return "design_drawing_evidence"
    return "live_state_record" if system_state is not None else None


def _attribution(combined: str, param: Optional[str]) -> Optional[str]:
    if param:
        return str(param)
    match = ATTRIBUTION_MENTION.search(combined)
    return match.group(0) if match else None


def _design_area_basis(combined: str, param: Optional[str]) -> Optional[str]:
    """`most_remote` / `most_demanding`, or None if absent OR conflated.

    Naming BOTH together (AC7's "the most-remote area is the same as the
    most-demanding area") resolves no single basis, exactly like naming
    neither (AC2) — both reach INV-FP-2 by two distinct routes.
    """
    if param in ("most_remote", "most_demanding"):
        return param
    mentions = {
        "most_remote" if "remote" in m.lower() else "most_demanding"
        for m in _DESIGN_AREA_MENTION.findall(combined)
    }
    if len(mentions) == 1:
        return next(iter(mentions))
    return None


def _design_area_analysed(combined: str, param: Optional[bool]) -> bool:
    return bool(param) or bool(_ANALYSED_MENTION.search(combined))


def _classification_value(combined: str, param: Optional[str]) -> Optional[str]:
    return str(param) if param else _classification_token(combined)


def _tested_assembly(combined: str, param: Optional[str]) -> Optional[str]:
    if param:
        return str(param)
    match = ASSEMBLY_MENTION.search(combined)
    return match.group(0) if match else None


def _code_edition_qualifier(combined: str, param: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """(qualifier value, asked_about value). The second is only set when a
    carry across TWO DISTINCT editions plus a carry verb is detected — never
    from counting mentions, since naming the same edition twice is what a
    correct answer looks like."""
    years = code_editions_mentioned(combined)
    if len(years) >= 2 and _CARRY_VERB.search(combined):
        return years[0], years[1]
    if param:
        return str(param), None
    if years:
        return years[0], None
    match = _CODE_EDITION_MENTION.search(combined)
    return (match.group(0) if match else None), None


def _building_qualifier(combined: str, configured: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """(qualifier value, asked_about value). Only set on the carry shape:
    'the similar/sister/comparable/identical building ... applies/carries'.
    Naming THIS building twice is a correct answer and must not fire."""
    if _SIMILAR_BUILDING.search(combined) and _CARRY_VERB.search(combined):
        return "other_building", (configured or "this_building")
    return None, None


def _basis_change_event(combined: str) -> str:
    lowered = combined.lower()
    if "tenant" in lowered:
        return "tenant_changed"
    if "commodity" in lowered:
        return "commodity_changed"
    if "layout" in lowered:
        return "layout_changed"
    return "basis_changed"


def _values(pattern: "re.Pattern", text: str) -> List[float]:
    out: List[float] = []
    for match in pattern.finditer(text or ""):
        value = float(match.group(1))
        if value not in out:
            out.append(value)
    return out


def _grounding(evidence: Sequence[str], *hints: Optional[str]) -> Tuple[str, Optional[str]]:
    """(origin, source_id). The first truthy hint wins; with nothing at all,
    the figure is a bare model statement — exactly what INV-FP-GROUNDING
    exists to catch."""
    if evidence:
        return "document", str(evidence[0])
    for hint in hints:
        if hint:
            return "document", str(hint)
    return "model", None


def _build_figures(
    query: str,
    answer: str,
    *,
    classification: Optional[str],
    classification_source: Optional[str],
    design_area_basis: Optional[str],
    design_area_analysed: Optional[bool],
    code_edition: Optional[str],
    tested_assembly_ref: Optional[str],
    flow_test: Optional[Dict[str, Any]],
    basis_changed_since: bool,
    evidence: Sequence[str],
    building: Optional[str],
    system_state: Optional[SystemState],
) -> Tuple[List[Figure], List[str]]:
    combined = f"{query} {answer}"
    figures: List[Figure] = []
    events: List[str] = []
    any_matched = False

    if CLASSIFICATION_WORDS.search(answer):
        any_matched = True
        attribution = _attribution(combined, classification_source)
        origin, source_id = _grounding(evidence, attribution)
        figures.append(Figure(
            quantity="hazard_classification", value=None, unit=None,
            origin=origin, source_id=source_id,
            source_class=_classification_source_class(combined, evidence, attribution),
            qualifiers={
                "classification_source": attribution,
                "classification": _classification_value(combined, classification),
            },
            text=combined,
        ))

    if DENSITY_WORDS.search(answer):
        any_matched = True
        attribution = _attribution(combined, classification_source)
        basis = _design_area_basis(combined, design_area_basis)
        analysed = _design_area_analysed(combined, design_area_analysed)
        edition, _ = _code_edition_qualifier(combined, code_edition)
        origin, source_id = _grounding(evidence, attribution, edition)
        classification_value = _classification_value(combined, classification)
        source_class = _density_source_class(combined, evidence, classification_value)
        qualifiers = {
            "design_area_basis": basis,
            "design_area_analysed": analysed,
            "classification": classification_value,
            "code_edition": edition,
            "classification_source": attribution,
        }
        values = _values(_DENSITY_VALUE, answer)
        if values:
            for value in values:
                figures.append(Figure(
                    quantity="design_density", value=value, unit="gpm/ft2",
                    origin=origin, source_id=source_id, source_class=source_class,
                    qualifiers=dict(qualifiers), text=combined,
                ))
        else:
            figures.append(Figure(
                quantity="design_density", value=None, unit=None,
                origin=origin, source_id=source_id, source_class=source_class,
                qualifiers=dict(qualifiers), text=combined,
            ))

    if RATING_WORDS.search(answer):
        any_matched = True
        assembly = _tested_assembly(combined, tested_assembly_ref)
        origin, source_id = _grounding(evidence, assembly)
        source_class = _rating_source_class(combined, evidence, assembly)
        values = _values(_RATING_VALUE, answer)
        qualifiers = {"tested_assembly_ref": assembly}
        if values:
            for value in values:
                figures.append(Figure(
                    quantity="fire_rating", value=value, unit="hours" if
                    re.search(r"\d\s*-?\s*hour", answer, re.IGNORECASE) else None,
                    origin=origin, source_id=source_id, source_class=source_class,
                    qualifiers=dict(qualifiers), text=combined,
                ))
        else:
            figures.append(Figure(
                quantity="fire_rating", value=None, unit=None,
                origin=origin, source_id=source_id, source_class=source_class,
                qualifiers=dict(qualifiers), text=combined,
            ))

    if SUPPLY_WORDS.search(f"{query} {answer}"):
        any_matched = True
        origin, source_id = _grounding(
            evidence,
            "current flow test" if flow_test is not None else None,
        )
        figures.append(Figure(
            quantity="water_supply", value=None, unit=None,
            origin=origin, source_id=source_id,
            source_class=_supply_source_class(combined, evidence, flow_test),
            qualifiers={}, text=combined,
        ))
        if flow_test is not None:
            valid_until = flow_test.get("valid_until")
            if valid_until is not None and valid_until < time.time():
                events.append("flow_test_expired")

    if COVERAGE_WORDS.search(f"{query} {answer}"):
        any_matched = True
        origin, source_id = _grounding(
            evidence, "live state reading" if system_state is not None else None,
        )
        figures.append(Figure(
            quantity="coverage_claim", value=None, unit=None,
            origin=origin, source_id=source_id,
            source_class=_coverage_source_class(combined, evidence, system_state),
            qualifiers={}, text=combined,
        ))

    if not any_matched and DESIGN_BASIS_WORDS.search(combined):
        attribution = _attribution(combined, classification_source)
        origin, source_id = _grounding(evidence, attribution)
        figures.append(Figure(
            quantity="design_basis_reference", value=None, unit=None,
            origin=origin, source_id=source_id, source_class=None,
            qualifiers={}, text=combined,
        ))

    # provenance: carry-across-an-entity, applied to every figure this call
    # built, since it is the same combined text driving all of them.
    building_value, building_asked = _building_qualifier(combined, building)
    edition_value, edition_asked = _code_edition_qualifier(combined, code_edition)
    for figure in figures:
        if building_value is not None:
            figure.qualifiers["building"] = building_value
            figure.asked_about["building"] = building_asked
        if edition_value is not None and "code_edition" not in figure.qualifiers:
            figure.qualifiers["code_edition"] = edition_value
        if edition_asked is not None:
            figure.asked_about["code_edition"] = edition_asked

    if basis_changed_since:
        events.append(_basis_change_event(combined))

    return figures, events


def _evaluate(figures: List[Figure], state: Dict[str, Any], events: List[str], now: float) -> Outcome:
    """H1 (authority), H2 (band, and unit_discipline again) and H3
    (grounding/qualifier/provenance/currency/derivation/unit_discipline)
    merged into one outcome.

    The five-hook pipeline separates these because a real host retrieves
    between H1 and H2/H3, and runs tool calls between H2 and H3. This host
    has no separate retrieval or tool-call phase — ``query`` and ``answer``
    arrive together — so all three hooks run over the same figures in one
    pass and their findings are combined into a single verdict, rather than
    silently dropping the H1-only kind (`authority`) or the H2-only kind
    (`band`) by calling ``answer_time`` alone.
    """
    ranking = _KIT.ranking(figures)
    tool_time = _KIT.tool_time(figures)
    answered = _KIT.answer_time(figures, state=state, events=events, now=now)
    findings = list(ranking.findings) + list(tool_time.findings) + list(answered.findings)
    outcome = Outcome(
        verdict=verdict_for(findings), findings=findings,
        hook=H3_ANSWER_TIME, kit=getattr(_KIT, "name", "fire_protection"),
    )
    outcome.incomplete = bool(ranking.incomplete or tool_time.incomplete or answered.incomplete)
    outcome.skipped = ranking.skipped + tool_time.skipped + answered.skipped
    return outcome


def _live_state(system_state: Optional[SystemState], now: float) -> Dict[str, Any]:
    # design_basis_revision and flow_test_record are the host's own
    # bookkeeping, not an external live system: they default to "on record
    # as of now" and go stale only through an explicit event, never through a
    # missing reading — the hand-written gate never treated "no flow_test
    # given" as UNKNOWN, only an EXPIRED one as stale.
    state: Dict[str, Any] = {
        "design_basis_revision": {"as_of": now},
        "flow_test_record": {"as_of": now},
    }
    # impairment_log / live_status are the genuine hard precondition (INV-3):
    # present only when the caller actually supplied that source, so an
    # absent source reports UNKNOWN with no design-basis fallback.
    if system_state is not None:
        if system_state.impairment_log is not None:
            state["impairment_log"] = {"as_of": system_state.fetched_at}
        if system_state.live_status is not None:
            state["live_status"] = {"as_of": system_state.fetched_at}
    return state


class FireProtectionReasoningBlock(UniversalBlock):
    name = "fire_protection_reasoning"
    version = "1.0.0"
    description = (
        "Deterministic fire protection & firefighting systems reasoning "
        "gate, driven by the shared kit_engine evaluator. Every statement "
        "passes INV-FP-1 (no hazard classification without a named engineer "
        "or an approved document), INV-FP-2 (density figures state "
        "most_remote or most_demanding, and which was actually analysed), "
        "INV-FP-3 (no coverage answer without a current impairment log AND "
        "current live status — a hard precondition), INV-FP-4 (a density "
        "figure carries classification, design area, code edition and "
        "classifier together), INV-FP-5 (fire rating answers carry the "
        "tested assembly, orientation and penetration detail, never the "
        "product alone), the REJECT_AS_PROOF authority ladder, provenance "
        "across buildings and code editions, the design-basis currency gate, "
        "grounding, unit discipline and two band checks. Go/no-go and "
        "named-person questions are refused BEFORE retrieval. Refused "
        "statements fail loud; nothing is invented."
    )
    layer = 3
    tags = ["fire_protection", "firefighting", "life_safety", "grounding", "gate"]
    requires: list = []

    async def process(self, input_data: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            query = str(input_data.get("query") or params.get("query") or "").strip()
            answer = str(input_data.get("answer") or params.get("answer") or "").strip()
            if not query or not answer:
                return _envelope("refused", error="query and answer are required")

            raw_state = input_data.get("system_state")
            if raw_state is None:
                system_state = None
            elif isinstance(raw_state, SystemState):
                system_state = raw_state
            elif isinstance(raw_state, dict):
                system_state = SystemState(
                    impairment_log=raw_state.get("impairment_log"),
                    live_status=raw_state.get("live_status"),
                    fetched_at=raw_state.get("fetched_at"),
                )
            else:
                return _envelope(
                    "refused",
                    error="system_state must be {impairment_log, live_status, fetched_at}",
                )

            evidence = input_data.get("evidence") or []
            if isinstance(evidence, str):
                evidence = [evidence]

            basis = FireProtectionBasis()

            # H0 — classify BEFORE building a single figure.
            scope_outcome = _KIT.pre_retrieval(query)
            if scope_outcome.verdict == "refused":
                result = scope_outcome.as_dict()
                result["interview_status"] = basis.interview_status
                result["unfilled_figures"] = basis.unfilled()
                return _envelope("success", result=result)

            figures, events = _build_figures(
                query, answer,
                classification=input_data.get("classification"),
                classification_source=input_data.get("classification_source"),
                design_area_basis=input_data.get("design_area_basis"),
                design_area_analysed=input_data.get("design_area_analysed"),
                code_edition=input_data.get("code_edition"),
                tested_assembly_ref=input_data.get("tested_assembly_ref"),
                flow_test=input_data.get("flow_test"),
                basis_changed_since=bool(input_data.get("basis_changed_since")),
                evidence=list(evidence),
                building=input_data.get("building"),
                system_state=system_state,
            )

            now = time.time()
            outcome = _evaluate(figures, _live_state(system_state, now), events, now)
            result = outcome.as_dict()
            result["interview_status"] = basis.interview_status
            result["unfilled_figures"] = basis.unfilled()
            return _envelope("success", result=result)
        except Exception as exc:  # noqa: BLE001 — a gate that dies silently is worse
            return _envelope("error", error=f"{type(exc).__name__}: {exc}")


__all__ = ["FireProtectionReasoningBlock"]
