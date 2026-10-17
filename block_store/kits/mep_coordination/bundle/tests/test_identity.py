"""identity: the regression pin for the "A__B" vs "A::B" incident.

clash_triage derived a clash id one way, version_diff derived it another
way, and both modules' unit tests passed -- each suite only ever checked its
own module's output against itself. score_proposals then silently reported
0.0 forever, because a proposal's clash_id never matched anything in
diff_versions' "resolved" bucket. The last two tests here are the actual
pin: they import both existing modules and assert their derivation agrees
with this one, on the same pair, so a future drift fails loudly instead of
three blocks downstream as a plausible-looking zero.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.blocks.identity import clash_id, element_key, pair_key


@dataclass
class El:
    global_id: str


def test_element_key_accepts_a_raw_string():
    assert element_key("A1") == "A1"


def test_element_key_accepts_an_object_with_global_id():
    assert element_key(El("B2")) == "B2"


def test_element_key_strips_whitespace():
    assert element_key("  A1\t\n") == "A1"
    assert element_key(El(" B2 ")) == "B2"


def test_element_key_raises_on_empty_string():
    with pytest.raises(ValueError):
        element_key("")
    with pytest.raises(ValueError):
        element_key("   ")


def test_element_key_raises_on_none():
    with pytest.raises(ValueError):
        element_key(None)


def test_element_key_raises_on_object_with_no_global_id():
    @dataclass
    class NoId:
        name: str = "nope"

    with pytest.raises(ValueError):
        element_key(NoId())


def test_pair_key_is_order_independent():
    """A clash between A and B is the same clash as between B and A."""
    assert pair_key("B1", "A1") == pair_key("A1", "B1")
    assert pair_key("A1", "B1") == ("A1", "B1")


def test_pair_key_works_on_element_objects_and_raw_ids_mixed():
    assert pair_key(El("B1"), "A1") == ("A1", "B1")


def test_clash_id_is_the_sorted_pair_joined_by_double_colon():
    assert clash_id("B1", "A1") == "A1::B1"
    assert clash_id("A1", "B1") == "A1::B1"


def test_clash_id_matches_clash_triage_clash_id_for():
    """The direct regression pin, half one: clash_triage's own derivation
    must agree with the canonical one for the same pair, in both orderings."""
    from app.blocks.clash_triage import clash_id_for

    assert clash_id_for("A1", "B1") == clash_id("A1", "B1")
    assert clash_id_for("B1", "A1") == clash_id("A1", "B1")


def test_clash_id_matches_version_diff_clash_id():
    """The direct regression pin, half two: version_diff's own derivation
    must agree with the canonical one for the same pair, in both orderings.

    This is exactly the comparison that was never made before the incident:
    clash_triage's id checked against clash_triage's own tests, version_diff's
    id checked against version_diff's own tests, and nobody ever put the two
    side by side until score_proposals did it silently in production.
    """
    from app.blocks.version_diff import _clash_id, _pair_key

    assert _clash_id(_pair_key("A1", "B1")) == clash_id("A1", "B1")
    assert _clash_id(_pair_key("B1", "A1")) == clash_id("A1", "B1")


def test_all_three_derivations_agree_on_the_same_pair():
    """All three, side by side, in one assertion -- the regression this
    entire module exists to prevent, stated as directly as possible."""
    from app.blocks.clash_triage import clash_id_for
    from app.blocks.version_diff import _clash_id, _pair_key

    a, b = "elementA", "elementB"
    canonical = clash_id(a, b)
    assert clash_id_for(a, b) == canonical
    assert _clash_id(_pair_key(a, b)) == canonical
    assert canonical == "elementA::elementB"
