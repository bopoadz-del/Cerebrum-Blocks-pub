"""Every pack formula carries id, source citation, domain_id, serves_verticals.

The Factory's ``store_coverage_index`` matches a vertical against a pack's
formulas; a formula that does not declare its own id, source, and domain is
unmatchable and un-auditable. This test is the CI check that fails a pack
formula missing any of them (ORDERS_08NOV_0545Z s1).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SLUG = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")


def _pack_formulas():
    out = []
    for path in sorted((REPO / "domain_packs").glob("*/pack.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for formula in data.get("formulas") or []:
            out.append((path, formula))
    return out


def test_every_pack_formula_carries_id_source_domain_and_serves():
    checked = 0
    for path, formula in _pack_formulas():
        fid = formula.get("formula_id") or formula.get("id") or path.name
        for field in ("id", "source", "domain_id", "serves_verticals"):
            assert field in formula, f"{path.name} {fid}: missing '{field}'"
            assert formula[field], f"{path.name} {fid}: empty '{field}'"
        serves = formula["serves_verticals"]
        assert isinstance(serves, list) and serves, f"{path.name} {fid}: serves_verticals must be non-empty"
        checked += 1
    assert checked >= 10, f"expected the known pack formulas, saw {checked}"


def test_pack_formula_domain_and_serves_are_slugs():
    for path, formula in _pack_formulas():
        fid = formula.get("formula_id") or formula.get("id") or path.name
        assert SLUG.match(str(formula["domain_id"])), f"{path.name} {fid}: bad domain_id {formula['domain_id']!r}"
        for v in formula["serves_verticals"]:
            assert SLUG.match(str(v)), f"{path.name} {fid}: bad serves_verticals {v!r}"
