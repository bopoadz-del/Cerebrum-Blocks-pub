"""K-S5 (ORDERS_29OCT_1750Z): client content out of the platform kits.

1. Every declarative kit's figure register ships NULL -- a filled register is
   one facility's interview and lives under tests/fixtures, never in app/.
2. No declarative kit keeps a hand-written duplicate gate beside it
   (app/blocks/<kit>/reasoning.py, app/blocks/<kit>_reasoning.py), a
   block_registry/<kit>_reasoning entry, or a certification for one.

Both checks are generic over whatever kits app/blocks declares; the checkers
are also exercised on synthetic trees, two inputs each.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from app.blocks.kit_engine.interview import load_design_basis

ROOT = pathlib.Path(__file__).resolve().parents[2]


def kit_dirs(root: pathlib.Path):
    return sorted(p.parent for p in (root / "app" / "blocks").glob("*/manifest.yaml")
                  if (p.parent / "invariants.yaml").is_file())


def filled_registers(root: pathlib.Path) -> dict:
    out = {}
    for d in kit_dirs(root):
        db = load_design_basis(d)
        if db is not None and (db.answered or db.facility):
            out[d.name] = sorted(db.answered) + ([f"facility={db.facility}"] if db.facility else [])
    return out


def duplicate_gates(root: pathlib.Path) -> list:
    certs_path = root / "block_certifications.json"
    certs = json.loads(certs_path.read_text(encoding="utf-8")) if certs_path.is_file() else {}
    certified = {b.get("block") for b in certs.get("blocks", [])}
    found = []
    for d in kit_dirs(root):
        k = d.name
        for rel in (f"app/blocks/{k}/reasoning.py", f"app/blocks/{k}_reasoning.py",
                    f"block_registry/{k}_reasoning"):
            if (root / rel).exists():
                found.append(rel)
        if f"{k}_reasoning" in certified:
            found.append(f"block_certifications.json:{k}_reasoning")
    return found


def test_every_platform_register_ships_null():
    assert kit_dirs(ROOT), "no declarative kits found"
    assert filled_registers(ROOT) == {}


def test_no_kit_keeps_a_hand_written_duplicate_gate():
    assert duplicate_gates(ROOT) == []


def test_the_filled_register_lives_in_the_fixtures():
    db = load_design_basis(ROOT / "tests" / "fixtures" / "kits" / "datacentre")
    assert db is not None and len(db.answered) == 17


# ---- checkers on synthetic trees -----------------------------------------
def _kit(root, name, values, facility=None):
    d = root / "app" / "blocks" / name
    d.mkdir(parents=True)
    (d / "manifest.yaml").write_text(f"kit: {name}\n", encoding="utf-8")
    (d / "invariants.yaml").write_text("invariants: []\n", encoding="utf-8")
    fig = "".join(f"  f{i}:\n    value: {v}\n    unit: u\n" for i, v in enumerate(values))
    fac = f"facility: {facility}\n" if facility else ""
    (d / "design_basis.yaml").write_text(fac + "design_basis:\n" + fig, encoding="utf-8")
    return d


@pytest.mark.parametrize("kits, expect", [
    ({"ka": ([None, None], None)}, {}),
    ({"ka": ([None, 3], None)}, {"ka": ["f1"]}),
    ({"kb": ([7, None], None), "kc": ([None], "site_x")}, {"kb": ["f0"], "kc": ["facility=site_x"]}),
])
def test_filled_registers_checker(tmp_path, kits, expect):
    for name, (values, fac) in kits.items():
        _kit(tmp_path, name, ["null" if v is None else v for v in values], fac)
    assert filled_registers(tmp_path) == expect


@pytest.mark.parametrize("extra, certs, expect", [
    ([], [], []),
    (["app/blocks/ka/reasoning.py"], [], ["app/blocks/ka/reasoning.py"]),
    (["app/blocks/kb_reasoning.py", "block_registry/kb_reasoning/block.json"], ["kb_reasoning"],
     ["app/blocks/kb_reasoning.py", "block_registry/kb_reasoning", "block_certifications.json:kb_reasoning"]),
])
def test_duplicate_gates_checker(tmp_path, extra, certs, expect):
    for name in ("ka", "kb"):
        _kit(tmp_path, name, ["null"])
    for rel in extra:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
    (tmp_path / "block_certifications.json").write_text(
        json.dumps({"blocks": [{"block": c} for c in certs]}), encoding="utf-8")
    assert sorted(duplicate_gates(tmp_path)) == sorted(expect)


# ---- the helper branches no real tree reaches (G6 9405a46 H1-H4) ----------
def _run(fn, root):
    """The checker's answer, or the exception it raised, as a comparable value:
    a crash on an input is a wrong answer, asserted, not a collection error."""
    try:
        return fn(root)
    except Exception as exc:  # noqa: BLE001 -- turned into an assertion below
        return f"raised {type(exc).__name__}"


@pytest.mark.parametrize("invariants_in, expect", [
    (("ka", "kz"), ["ka", "kz"]),
    (("ka",), ["ka"]),          # kz has manifest.yaml but no invariants.yaml: not a kit
])
def test_kit_dirs_needs_invariants_beside_the_manifest(tmp_path, invariants_in, expect):
    for name in ("ka", "kz"):
        d = _kit(tmp_path, name, ["null"])
        if name not in invariants_in:
            (d / "invariants.yaml").unlink()
    assert [p.name for p in _run(kit_dirs, tmp_path)] == expect


@pytest.mark.parametrize("with_basis, expect", [
    (True, {"ka": ["f0"]}),
    (False, {}),                # no design_basis.yaml: nothing to be filled
])
def test_filled_registers_skips_a_kit_with_no_register(tmp_path, with_basis, expect):
    d = _kit(tmp_path, "ka", [5])
    if not with_basis:
        (d / "design_basis.yaml").unlink()
    assert _run(filled_registers, tmp_path) == expect


@pytest.mark.parametrize("certs_text, expect", [
    (None, []),                                         # no certifications file
    ("{}", []),                                         # a certs file with no blocks key
    ('{"blocks": [{"block": "ka_reasoning"}]}', ["block_certifications.json:ka_reasoning"]),
])
def test_duplicate_gates_reads_certifications_only_when_they_exist(tmp_path, certs_text, expect):
    _kit(tmp_path, "ka", ["null"])
    if certs_text is not None:
        (tmp_path / "block_certifications.json").write_text(certs_text, encoding="utf-8")
    assert _run(duplicate_gates, tmp_path) == expect
