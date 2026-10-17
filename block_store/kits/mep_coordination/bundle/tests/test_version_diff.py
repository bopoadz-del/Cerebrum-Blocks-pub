"""version_diff: the three tests + mutation probe required per block.

Findings are built directly as dataclass instances -- no mesh, no IFC, no
mocks. diff_versions and score_proposals only ever look at plain fields
(element_a/b, kind) and plain dicts, so a real Finding is exactly as cheap
to construct here as a fake one would be.
"""
from __future__ import annotations

from app.blocks.geometry_engine import Finding
from app.blocks.version_diff import diff_versions, score_proposals


def _finding(a, b, kind, **overrides):
    fields = dict(element_a=a, element_b=b, kind=kind, method="min_distance")
    fields.update(overrides)
    return Finding(**fields)


def test_happy_new_resolved_regressed_persisting_each_land_correctly():
    """One of each planted outcome, in one diff:
    (A,B) a clash in v1 that disappears in v2       -> resolved
    (C,D) clear in v1, a clash in v2                -> regressed
    (E,F) a clash in both                           -> persisting
    (G,H) a clearance violation only in v2           -> new
    """
    v1 = [
        _finding("A", "B", "clash"),
        _finding("C", "D", "clear", required_clearance_m=0.5, distance_m=1.2),
        _finding("E", "F", "clash"),
    ]
    v2 = [
        _finding("E", "F", "clash"),
        _finding("C", "D", "clash"),
        _finding("G", "H", "clearance", required_clearance_m=0.5, distance_m=0.2, rule_id="R1"),
    ]

    diff = diff_versions(v1, v2)

    assert [e["clash_id"] for e in diff["resolved"]] == ["A::B"]
    assert [e["clash_id"] for e in diff["regressed"]] == ["C::D"]
    assert [e["clash_id"] for e in diff["persisting"]] == ["E::F"]
    assert [e["clash_id"] for e in diff["new"]] == ["G::H"]


def test_unordered_pair_swap_is_persisting_not_resolved_plus_new():
    """Planted failure, visible: the same clash reported as (A,B) in v1 and
    (B,A) in v2 is physically one clash that never went away. A keying bug
    would instead report it as one resolved clash (A,B) plus one brand-new
    clash (B,A) -- exactly the double-count this block exists to prevent."""
    v1 = [_finding("A", "B", "clash")]
    v2 = [_finding("B", "A", "clash")]

    diff = diff_versions(v1, v2)

    assert len(diff["persisting"]) == 1
    assert diff["persisting"][0]["clash_id"] == "A::B"
    assert diff["resolved"] == []
    assert diff["new"] == []


def test_mutation_probe_ordered_key_breaks_the_swap_detection():
    """Proves test (b) above is actually exercising the unordered-pair rule
    and not passing by accident: redo the same match with an ORDERED pair
    as the key (the mutation) and show it fails exactly the assertions
    test (b) makes -- the swapped clash is lost as "resolved" + "new"
    instead of recognised as one persisting clash."""

    def _ordered_diff(findings_v1, findings_v2):
        # Deliberately broken: no sorted() around the pair, unlike the real
        # _pair_key in version_diff.py.
        v1_by_key = {(f.element_a, f.element_b): f for f in findings_v1}
        v2_by_key = {(f.element_a, f.element_b): f for f in findings_v2}
        resolved, new, persisting = [], [], []
        for key in set(v1_by_key) | set(v2_by_key):
            in_v1, in_v2 = key in v1_by_key, key in v2_by_key
            if in_v1 and not in_v2:
                resolved.append(key)
            elif in_v2 and not in_v1:
                new.append(key)
            elif in_v1 and in_v2:
                persisting.append(key)
        return {"resolved": resolved, "new": new, "persisting": persisting}

    v1 = [_finding("A", "B", "clash")]
    v2 = [_finding("B", "A", "clash")]

    broken = _ordered_diff(v1, v2)

    # The mutated (ordered-key) version fails test (b)'s expectations: it
    # sees no persisting match at all, and instead manufactures a false
    # resolution plus a false new clash.
    assert broken["persisting"] == []
    assert len(broken["resolved"]) == 1
    assert len(broken["new"]) == 1

    # Meanwhile the real, unordered-key implementation gets it right on the
    # identical fixture -- confirming the difference is the key, not the data.
    correct = diff_versions(v1, v2)
    assert len(correct["persisting"]) == 1
    assert correct["resolved"] == []
    assert correct["new"] == []


def test_score_proposals_rate_and_zero_proposals_guard():
    diff = {
        "resolved": [{"clash_id": "A::B"}, {"clash_id": "C::D"}],
        "new": [], "regressed": [], "persisting": [],
    }

    scored = score_proposals(
        [{"clash_id": "A::B"}, {"clash_id": "X::Y"}], diff,
    )
    assert scored == {"proposed": 2, "resolved": 1, "rate": 0.5}

    # Must not crash on an empty proposal list -- and must report 0.0, not
    # skip the "rate" key or raise ZeroDivisionError.
    empty_scored = score_proposals([], diff)
    assert empty_scored == {"proposed": 0, "resolved": 0, "rate": 0.0}
