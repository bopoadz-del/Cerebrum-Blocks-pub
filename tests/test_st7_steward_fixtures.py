"""ST-7: the three steward mini fixtures honour the loader's row contract.

The contract is read from the real loader source,
``block_store/kits/private_estate_operations/steward_runtime/packs/__init__.py``
(installed as ``app.steward.packs``), not restated here:

  * required = keys the loader subscripts (``row["k"]``),
  * allowed  = required + keys it reads with ``row.get("k")``,
  * type     = the ORM column the key feeds (``Mapped[...]`` in ``models.py``),
  * money    = keys the loader passes through ``parse_money``; the value must
               parse with the real ``steward_runtime/money.py`` helper.

The loader functions themselves cannot be executed here: they need
sqlalchemy + pgvector, which this repo's CI does not install, so the contract
is taken from their AST instead of from a run.
"""
from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "block_store/kits/private_estate_operations/steward_runtime"
PACKS = RUNTIME / "packs"
LOADER_SRC = PACKS / "__init__.py"
MODELS_SRC = RUNTIME / "models.py"

# (loader function, pack id, fixture file, ORM class the rows become)
FIXTURES = (
    ("load_hospitality_intents_mini", "steward_hospitality_intents_v1", "intents.jsonl", "HospitalityIntent"),
    ("load_facilities_mini", "steward_facilities_open_v1", "assets.jsonl", "FacilityAsset"),
    ("load_fleet_mini", "steward_fleet_open_v1", "vehicles.jsonl", "FleetVehicle"),
)

_spec = importlib.util.spec_from_file_location("st7_steward_money", RUNTIME / "money.py")
_money = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_money)
parse_money = _money.parse_money

_PYTYPES = {"str": str, "int": int, "Decimal": object, "bool": bool}


def _row_key(node):
    """('req'|'opt', key) when ``node`` is row["k"] / row.get("k")."""
    if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
            and node.value.id == "row" and isinstance(node.slice, ast.Constant)):
        return "req", node.slice.value
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get" and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "row" and node.args
            and isinstance(node.args[0], ast.Constant)):
        return "opt", node.args[0].value
    return None


def _column_types(models_src: str, cls: str) -> dict:
    """column -> (base type name, nullable) from ``Mapped[...]`` annotations."""
    tree = ast.parse(models_src)
    out = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == cls:
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    inner = stmt.annotation.slice
                    nullable = isinstance(inner, ast.Subscript) and inner.value.id == "Optional"
                    base = inner.slice if nullable else inner
                    out[stmt.target.id] = (getattr(base, "id", "object"), nullable)
    return out


def loader_contract(loader_src: str, models_src: str, func: str, cls: str) -> dict:
    """key -> {"required", "type", "nullable", "money"} for rows ``func`` reads."""
    tree = ast.parse(loader_src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == func)
    columns = _column_types(models_src, cls)
    contract = {}
    for call in ast.walk(fn):
        if not (isinstance(call, ast.Call) and getattr(call.func, "id", None) == cls):
            continue
        for kw in call.keywords:
            for sub in ast.walk(kw.value):
                hit = _row_key(sub)
                if hit is None:
                    continue
                kind, key = hit
                money = any(isinstance(c, ast.Call) and getattr(c.func, "id", None) == "parse_money"
                            for c in ast.walk(kw.value))
                base, nullable = columns[kw.arg]
                contract[key] = {"required": kind == "req", "type": base,
                                 "nullable": nullable or kind == "opt", "money": money}
    # tenant/estate scope keys are subscripted outside the ORM call
    for sub in ast.walk(fn):
        hit = _row_key(sub)
        if hit and hit[1] not in contract:
            contract[hit[1]] = {"required": hit[0] == "req", "type": "str",
                                "nullable": hit[0] == "opt", "money": False}
    return contract


def contract_errors(row: dict, contract: dict) -> list:
    errs = []
    for key, spec in contract.items():
        if spec["required"] and key not in row:
            errs.append(f"missing required {key}")
    for key, value in row.items():
        spec = contract.get(key)
        if spec is None:
            errs.append(f"unknown field {key}")
            continue
        if value is None:
            if not spec["nullable"]:
                errs.append(f"null {key}")
            continue
        if spec["money"]:
            if isinstance(value, bool) or parse_money(value) is None:
                errs.append(f"unparseable money {key}")
            continue
        want = _PYTYPES[spec["type"]]
        if isinstance(value, bool) and want is not bool or not isinstance(value, want):
            errs.append(f"wrong type {key}")
    return errs


def _contract(func, cls):
    return loader_contract(LOADER_SRC.read_text(encoding="utf-8"),
                           MODELS_SRC.read_text(encoding="utf-8"), func, cls)


def _rows(pack, name):
    lines = (PACKS / pack / "mini" / name).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


@pytest.mark.parametrize("func,pack,name,cls", FIXTURES)
def test_fixture_rows_match_the_loader_contract(func, pack, name, cls):
    rows = _rows(pack, name)
    assert rows, f"{pack}/mini/{name} has no rows"
    contract = _contract(func, cls)
    assert [(i, e) for i, r in enumerate(rows) for e in contract_errors(r, contract)] == []


@pytest.mark.parametrize("func,pack,name,cls", FIXTURES)
def test_fixture_is_labelled_synthetic(func, pack, name, cls):
    readme = (PACKS / pack / "mini" / "README.md").read_text(encoding="utf-8")
    assert "SYNTHETIC TEST FIXTURE" in readme and name in readme
    assert all("synth" in json.dumps(r).lower() for r in _rows(pack, name))


@pytest.mark.parametrize("func,cls,required", [
    ("load_facilities_mini", "FacilityAsset", {"tenant_id", "estate_id", "asset_label"}),
    ("load_fleet_mini", "FleetVehicle", {"tenant_id", "estate_id", "vin_or_internal_id"}),
    ("load_hospitality_intents_mini", "HospitalityIntent", set()),
])
def test_contract_required_keys_come_from_the_loader(func, cls, required):
    assert {k for k, s in _contract(func, cls).items() if s["required"]} == required


@pytest.mark.parametrize("row,expected", [
    ({"tenant_id": "t", "estate_id": "e", "vin_or_internal_id": "SYNTH-1", "year": 2020}, []),
    ({"tenant_id": "t", "estate_id": "e", "year": 2020}, ["missing required vin_or_internal_id"]),
    ({"tenant_id": "t", "estate_id": "e", "vin_or_internal_id": "SYNTH-1", "colour": "red"},
     ["unknown field colour"]),
    ({"tenant_id": "t", "estate_id": "e", "vin_or_internal_id": "SYNTH-1", "year": "2020"},
     ["wrong type year"]),
])
def test_fleet_row_contract_two_inputs_two_results(row, expected):
    assert contract_errors(row, _contract("load_fleet_mini", "FleetVehicle")) == expected


@pytest.mark.parametrize("cost,expected", [
    ("1250.00", []),
    ("twelve", ["unparseable money cost"]),
])
def test_facility_money_parses_like_the_loader(cost, expected):
    row = {"tenant_id": "t", "estate_id": "e", "asset_label": "SYNTH a", "cost": cost}
    assert contract_errors(row, _contract("load_facilities_mini", "FacilityAsset")) == expected
