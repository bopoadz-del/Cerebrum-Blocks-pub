"""Block-manifest ``trust_tier``: a provenance claim, not publisher reputation.

Pin: mirrors <private-repo> ``backend/app/factory/compliance_gate.py``
``ACCEPTED_TRUST_TIERS`` at factory commit ``eacc254``.

Factory is not a submodule or workspace dependency of this repo. Do not
import it. ``load_blocks_registry`` lives only in <private-repo>
``backend/app/factory/dual_registry.py`` and currently leaves
``BlockRef.trust_tier`` empty for refs loaded from this registry (it reads
the Factory shelf only). Teaching that loader to read this field is a
Factory change.

This field is NOT ``publisher_tier`` (``certified`` / ``reviewed`` /
``community`` / ``revoked``). ``publisher_tier`` is a platform assertion
about the *publisher*. ``trust_tier`` is a provenance claim about the
*block*:

- ``platform`` — the block ships inside this repository
- ``contributor_reviewed`` — a named reviewer signed it off
"""

from __future__ import annotations

from typing import Any, Dict, List

# Literal pin to <private-repo> backend/app/factory/compliance_gate.py @ eacc254
ACCEPTED_TRUST_TIERS = frozenset({"platform", "contributor_reviewed"})

REASON_MISSING_TRUST_TIER = "missing required manifest field: trust_tier"


def check_trust_tier(manifest: Dict[str, Any]) -> List[str]:
    """Return reasons if ``trust_tier`` is missing or not an accepted value."""
    if "trust_tier" not in manifest:
        return [REASON_MISSING_TRUST_TIER]

    raw = manifest["trust_tier"]
    if raw is None or raw == "":
        return [REASON_MISSING_TRUST_TIER]
    if not isinstance(raw, str):
        return [
            "invalid trust_tier: %r is not a string (accepted: %s)"
            % (raw, ", ".join(sorted(ACCEPTED_TRUST_TIERS)))
        ]
    tier = raw.strip()
    if tier not in ACCEPTED_TRUST_TIERS:
        return [
            "invalid trust_tier: %r (accepted: %s)"
            % (raw, ", ".join(sorted(ACCEPTED_TRUST_TIERS)))
        ]
    return []
