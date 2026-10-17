"""Parity pin: Cerebrum-Blocks ``credibility.py`` vs the shared ladder literal.

This string is copied identically into <private-repo>
``backend/tests/test_knowledge_ranking.py``. A unilateral edit of the tier
map or CERTIFIED_MIN_ACCURACY fails CI unless BOTH copies of this literal
are updated together.
"""

from __future__ import annotations

from app.core.credibility import CredibilityScorer, CredibilityTier

# Dual-register pin. Must stay byte-identical with <private-repo>
# ``backend/tests/test_knowledge_ranking.py::CREDIBILITY_LADDER_LITERAL``.
CREDIBILITY_LADDER_LITERAL = (
    "CERTIFIED=1,OPERATIONAL=2,EXPERIMENTAL=3,UNVERIFIED=4,QUARANTINE=5;"
    "CERTIFIED_MIN_ACCURACY=0.95"
)


def _parse_credibility_ladder_literal(literal: str) -> tuple[dict[str, int], float]:
    """Split the shared pin into a tier map and CERTIFIED_MIN_ACCURACY."""
    tier_blob, acc_blob = literal.split(";")
    tiers = {}
    for item in tier_blob.split(","):
        name, raw = item.split("=")
        tiers[name] = int(raw)
    acc_name, acc_raw = acc_blob.split("=")
    assert acc_name == "CERTIFIED_MIN_ACCURACY"
    return tiers, float(acc_raw)


def test_credibility_py_matches_shared_literal():
    """``app.core.credibility`` tier map + CERTIFIED_MIN_ACCURACY match the pin."""
    tiers, certified_min = _parse_credibility_ladder_literal(CREDIBILITY_LADDER_LITERAL)
    for name, value in tiers.items():
        assert int(getattr(CredibilityTier, name)) == value, name
    assert CredibilityScorer.CERTIFIED_MIN_ACCURACY == certified_min
    assert CredibilityTier.CERTIFIED < CredibilityTier.QUARANTINE
    assert tiers["CERTIFIED"] < tiers["QUARANTINE"]
