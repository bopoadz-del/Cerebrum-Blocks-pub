"""Sports venue kit — the companion the refusal tests cannot provide.

Every other suite that touches this kit asserts a REFUSAL.
``test_every_invariant_bites.py`` proves each of the 46 records fires, by id.
``test_reasoning_kits.py`` proves eight cross-kit properties — the kit loads, it
refuses its scope questions before retrieval, an ungrounded figure is never waved
through, an undeclared qualifier is refused.

All of those pass if the kit refuses EVERYTHING. That is the failure this file
exists to catch: forty-six records at ``severity: refuse`` and no test anywhere
proving the kit ever says yes. A platform that refuses every question looks
exactly like a working gate — it reports fail-closed, which reads as correct
behaviour — and the only thing that separates a gate from a wall is a figure that
gets through.

So the centre of this file is ``test_a_properly_qualified_capacity_passes_every
_hook``. The rest asserts the domain distinctions the kit exists for: the same
number means different things across the four archetypes, and a touring event is
a guest in someone else's building.
"""
from __future__ import annotations

import pathlib
import time

import pytest

from app.blocks.kit_engine import Figure, load_kit

KIT_DIR = pathlib.Path(__file__).resolve().parents[2] / "app" / "blocks" / "stadium_venue"


@pytest.fixture(scope="module")
def kit():
    return load_kit(KIT_DIR)


def _state(*providers: str, now: float = None) -> dict:
    """A live-state reading for each named provider.

    Presence is what currency needs here: every window in this kit declares
    ``max_age: event``, which is an EVENT boundary and not a number of seconds,
    so the evaluator checks that the provider could be read at all. A provider
    that cannot be read is UNKNOWN and never falls back to the design basis.
    """
    moment = now if now is not None else time.time()
    return {name: {"as_of": moment, "value": "ok"} for name in providers}


#: Everything a licensed-capacity figure must carry to be usable. Spelled out
#: rather than built by a helper, because this dict IS the answer to "what does
#: this kit demand before it will let a capacity through", and a reader who wants
#: that answer should not have to reconstruct it from eleven separate records.
CAPACITY_QUALIFIERS = {
    "archetype": "A_fixed_championship",
    "governing_body": "UEFA",
    "venue_id": "V-001",
    "config_type": "football",
    "event_state": "event_day",
    "operational_phase": "championships",
    "safety_certificate_ref": "SC-2026-014",
    # Capacity is not a seat count: it is usable seats x lower(P, S). Without
    # both factors the number is a seating chart, not a licensed capacity.
    "p_factor": 1.0,
    "s_factor": 0.95,
}

CAPACITY_STATE = ("event_configuration", "stands_open", "tenant_schedule")


def _capacity(**overrides) -> Figure:
    fields = dict(
        quantity="event_capacity", value=52000, unit="persons",
        origin="document", source_id="SC-2026-014",
        source_class="safety_certificate", revision="C",
        effective_date="2026-09-01", qualifiers=dict(CAPACITY_QUALIFIERS),
        # A licensed capacity under a safety certificate IS safety-critical, and the
        # HOST sets this — no invariant guesses a claim class from prose, because
        # guessing it is the defect. Three identity records apply only to this class
        # by the owner's own design; see the labelling test below for what that costs.
        claim_class="safety_critical",
    )
    fields.update(overrides)
    return Figure(**fields)


# --- the companion: the kit says yes ----------------------------------------

def test_a_properly_qualified_capacity_passes_every_hook(kit):
    """The one assertion 52 other tests cannot make.

    If this fails while everything else passes, the kit is a wall: it refuses
    correctly formed figures, every refusal test still goes green, and the
    platform reports fail-closed while answering nothing.
    """
    figure = _capacity()
    state = _state(*CAPACITY_STATE)

    for hook, outcome in (
        ("H1", kit.ranking([figure])),
        ("H2", kit.tool_time([figure])),
        ("H3", kit.answer_time([figure], state, [])),
        ("H4", kit.export_time([figure], state, [])),
    ):
        assert outcome.verdict != "refused", (
            f"{hook} refused a fully qualified, sourced, current capacity: "
            + "; ".join(f"{f.invariant_id}: {f.message}" for f in outcome.findings)
        )


def test_the_passing_figure_is_not_passing_because_nothing_ran(kit):
    """Guard on the guard above.

    A hook that selects no invariants also returns "pass", so the companion test
    would go green against a kit that had quietly stopped governing capacity at
    all — which is how the H4 mapping defect hid: records declared at H4 were
    selected at no hook, and every H4 outcome was a vacant pass.
    """
    assert kit.at("H1"), "H1 selected no invariants"
    assert kit.at("H2"), "H2 selected no invariants"
    assert kit.at("H3"), "H3 selected no invariants"
    assert kit.at("H4"), "H4 selected no invariants"

    governing = [inv for inv in kit.at("H3") if inv.governs(_capacity())]
    assert len(governing) >= 5, (
        f"only {len(governing)} H3 records govern a capacity figure — the passing "
        f"test above would be measuring almost nothing"
    )


# --- one removal each, to prove the pass was earned -------------------------

@pytest.mark.parametrize("dropped", sorted(CAPACITY_QUALIFIERS))
def test_removing_any_single_qualifier_refuses(kit, dropped):
    """Each qualifier in the passing figure is load-bearing.

    Without this, the companion test could be passing because the kit demands
    less than it claims: a figure carrying ten qualifiers passes, and so would a
    figure carrying two, and nothing would distinguish them.
    """
    qualifiers = {k: v for k, v in CAPACITY_QUALIFIERS.items() if k != dropped}
    outcome = kit.answer_time(
        [_capacity(qualifiers=qualifiers)], _state(*CAPACITY_STATE), [])
    assert outcome.verdict == "refused", (
        f"dropping {dropped} changed nothing — it is declared but not enforced"
    )


@pytest.mark.parametrize("dropped", CAPACITY_STATE)
def test_removing_any_single_state_provider_refuses(kit, dropped):
    """Live state has no design-basis fallback: a design figure is not a current
    state, and a provider that cannot be read is UNKNOWN, not "probably fine"."""
    providers = tuple(p for p in CAPACITY_STATE if p != dropped)
    outcome = kit.answer_time([_capacity()], _state(*providers), [])
    assert outcome.verdict == "refused", (
        f"{dropped} was unreadable and the capacity was still asserted"
    )


def test_an_uncited_capacity_is_refused_by_grounding(kit):
    """The hole this kit shipped with. A model-origin figure with no source_id
    passed all 43 other records — qualified, in band, in date, uncarried — and
    nothing asked where the number came from."""
    outcome = kit.answer_time(
        [_capacity(origin="model", source_id=None, source_class=None)],
        _state(*CAPACITY_STATE), [])
    assert outcome.verdict == "refused"
    ids = [f.invariant_id for f in outcome.findings]
    assert "INV-SV-GROUNDING" in ids, f"grounding did not fire: {ids}"


def test_a_stale_capacity_is_refused_when_the_configuration_changed(kit):
    """Currency in this domain is an EVENT, not a clock: the certificate was
    varied or the configuration changed, so the number stopped being true
    regardless of how recently it was written down."""
    outcome = kit.answer_time(
        [_capacity()], _state(*CAPACITY_STATE), ["config_change"])
    assert outcome.verdict == "refused"
    assert any("stale" in (f.message or "").lower() for f in outcome.findings)


# --- the domain distinction the kit exists for ------------------------------

def test_a_figure_carried_between_archetypes_is_refused(kit):
    """The reason this is not "one stadium".

    A fixed championship venue, a multi-tenant venue, a single-purpose venue and
    a TOURING event mean different things by the same number. Carrying one
    across is the defect the four archetypes exist to catch.
    """
    carried = _capacity(derivations=["carry_fixed_venue_to_road"])
    outcome = kit.answer_time([carried], _state(*CAPACITY_STATE), [])
    assert outcome.verdict == "refused"
    assert any(f.kind == "provenance" for f in outcome.findings)


def test_a_figure_carried_between_configurations_is_refused(kit):
    """Licensed capacity is configuration-conditioned. A football number quoted
    for a concert is a different building with the same postcode."""
    carried = _capacity(derivations=["carry_football_to_concert"])
    outcome = kit.answer_time([carried], _state(*CAPACITY_STATE), [])
    assert outcome.verdict == "refused"
    assert any(f.kind == "provenance" for f in outcome.findings)


# --- H0: refused before retrieval, but not everything -----------------------

@pytest.mark.parametrize("question", [
    "can we start the match",
    "is the pitch playable",
    "can we sell full capacity",
    "can we rig this load",
    "can we open the stand",
    "can we override a turnstile",
    "can we accept a reduced stewarding ratio",
    "can we proceed at this tour stop",
])
def test_an_operational_go_decision_is_refused_before_retrieval(kit, question):
    """No document makes a go/no-go answerable, so retrieving at all is wrong:
    it returns citations that read as though they authorised the decision."""
    outcome = kit.pre_retrieval(question)
    assert outcome.verdict == "refused", f"not refused at H0: {question!r}"
    assert any(f.invariant_id.startswith("SCOPE:") for f in outcome.findings)
    # The refusal has to name who does decide, or it is an unhelpful no.
    assert any(f.message for f in outcome.findings)


@pytest.mark.parametrize("question", [
    "what is the licensed capacity in the football configuration",
    "what does the safety certificate say about exit width",
    "what is the measured horizontal lux for this venue",
    "which standard governs pitch hardness testing",
    "what is the certified capacity of rigging point R-12",
])
def test_an_ordinary_venue_question_reaches_retrieval(kit, question):
    """The other half of the scope gate, and the half that can silently rot.

    Thirteen patterns refuse before retrieval. If those patterns were too broad
    they would swallow ordinary document questions, every refusal test would
    still pass, and the platform would answer nothing while looking careful.
    """
    outcome = kit.pre_retrieval(question)
    assert outcome.verdict != "refused", (
        f"H0 refused an ordinary document question: {question!r} — "
        + "; ".join(f.message or "" for f in outcome.findings)
    )


# --- the register reports honestly -----------------------------------------

def test_no_interview_has_run_and_the_kit_says_so(kit):
    """25 open figures and no owner question sheet. The kit must report that as
    an un-interviewed domain, never as figures it holds."""
    assert kit.design_basis is not None, "the kit lost its figure register"
    assert kit.interview is None, (
        "a questions.yaml appeared for stadium_venue — if a domain owner supplied "
        "one, this test should be updated to assert their wording is carried"
    )
    assert kit.design_basis.answered == (), (
        f"values appeared with no interview: {kit.design_basis.answered}"
    )
    assert len(kit.design_basis.open) == 25


# --- what the claim_class design costs, pinned so it stays visible -----------

def test_an_unlabelled_figure_skips_the_identity_records(kit):
    """A deliberate design consequence, asserted so it is a decision and not a bug.

    Three records — INV-SV-ARCHETYPE, INV-SV-QUAL-CONFIG, INV-SV-QUAL-EVENT-STATE —
    apply only to ``claim_class: safety_critical``, per the G2 spec. The engine never
    guesses a claim class from prose, correctly, so a figure the HOST does not label
    is not governed by those three: it can be asserted with no archetype, no venue_id
    and no event_state.

    That is the owner's call and it is the right shape for records about the moment a
    figure describes. It is pinned here because the cost is invisible otherwise: the
    figure passes, nothing is logged, and the identity rules simply do not run. If a
    host is ever found shipping unlabelled venue figures, THIS is the test that says
    what happens next, and the fix is in the host's labelling, not in the kit.
    """
    unlabelled = _capacity(claim_class=None, qualifiers={
        k: v for k, v in CAPACITY_QUALIFIERS.items()
        if k not in ("archetype", "governing_body", "venue_id",
                     "config_type", "event_state", "operational_phase")
    })
    governing = [inv.id for inv in kit.at("H3") if inv.governs(unlabelled)]
    for record in ("INV-SV-ARCHETYPE", "INV-SV-QUAL-CONFIG", "INV-SV-QUAL-EVENT-STATE"):
        assert record not in governing, (
            f"{record} now governs an unlabelled figure. If that was intended, this "
            f"test should be deleted and the identity gate documented as unconditional"
        )

    # It is still not waved through — the records that do NOT depend on a host label
    # catch it, which is why the design is defensible rather than merely documented.
    outcome = kit.answer_time([unlabelled], _state(*CAPACITY_STATE), [])
    assert outcome.verdict == "refused", (
        "an unlabelled capacity missing every identity field passed entirely — the "
        "claim_class design is only acceptable while the unlabelled path is still "
        "governed by something"
    )
