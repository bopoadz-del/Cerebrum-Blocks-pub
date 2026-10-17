"""A kit declares the verticals it serves; the Factory reads it, never a table.

The Factory used to keep its own vertical -> kit tables (READY_VERTICALS,
EXCLUDED_VERTICALS, VERTICAL_TO_KIT). A committed copy of Store facts goes
stale -- ``stadium_venue`` shipped here and every stadium build took the
no-kit path. The facts now live on the kit that owns them:

* ``serves_verticals`` -- vertical slugs this kit answers for (domain kits in
  ``block_store/kits/*/manifest.json``, reasoning kits in
  ``app/blocks/*/manifest.yaml``);
* ``build_ready`` -- the operator's declaration that a domain kit is ready to
  build against (domain kits only);
* ``excludes_verticals`` -- vertical slugs this kit declares OUT of its
  coverage; the Factory resolves them UNSUPPORTED and names this kit.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
SLUG = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")


def _declared():
    out = []
    for p in sorted((REPO / "block_store" / "kits").glob("*/manifest.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if "serves_verticals" in data:
            out.append((p.parent.name, data))
    for p in sorted((REPO / "app" / "blocks").glob("*/manifest.yaml")):
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if "serves_verticals" in data:
            out.append((p.parent.name, data))
    return out


def test_serves_verticals_are_slugs_and_owned_by_one_kit():
    owner = {}
    declared = _declared()
    assert declared, "no kit declares serves_verticals"
    for kit, data in declared:
        verticals = data["serves_verticals"]
        assert isinstance(verticals, list) and verticals, kit
        for v in verticals:
            assert SLUG.match(v), (kit, v)
            assert owner.setdefault(v, kit) == kit, f"{v} served by {owner[v]} and {kit}"


def test_build_ready_is_a_boolean_where_declared():
    for kit, data in _declared():
        if "build_ready" in data:
            assert isinstance(data["build_ready"], bool), kit


def test_excluded_verticals_are_slugs_and_served_by_no_kit():
    declared = _declared()
    served = {v for _, data in declared for v in data.get("serves_verticals") or []}
    excluded = []
    for p in sorted((REPO / "block_store" / "kits").glob("*/manifest.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        for v in data.get("excludes_verticals") or []:
            assert SLUG.match(v), (p.parent.name, v)
            excluded.append(v)
    assert not set(excluded) & served, sorted(set(excluded) & served)
