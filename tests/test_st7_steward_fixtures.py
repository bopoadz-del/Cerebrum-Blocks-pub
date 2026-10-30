"""ST-7: the three steward mini fixtures honour the loader's row contract.

The contract is read from the real loader source,
``block_store/kits/private_estate_operations/steward_runtime/packs/__init__.py``
(installed as ``app.steward.packs``), not restated here:

  * required = keys the loader subscripts (``row["k"]``),
  * allowed  = required + keys it reads with ``row.get("k")``,
  * type     = the ORM column the key feeds (``Mapped[...]`` in ``models.py``),
  * nullable = that column is ``Mapped[Optional[...]]`` in ``models.py``, or the
               loader coalesces the value (``row.get("k") or default``). A
               ``row.get("k")`` feeding a non-Optional column with no default
               must be present and non-null (absent == None == NULL insert),
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
                base, column_nullable = columns[kw.arg]
                nullable = column_nullable or _coalesced(kw.value, sub)
                contract[key] = {"required": kind == "req", "type": base,
                                 "nullable": nullable, "money": money}
    # tenant/estate scope keys are subscripted outside the ORM call and feed
    # the same-named column
    for sub in ast.walk(fn):
        hit = _row_key(sub)
        if hit and hit[1] not in contract:
            base, column_nullable = columns.get(hit[1], ("str", False))
            contract[hit[1]] = {"required": hit[0] == "req",
                                "type": base, "nullable": column_nullable, "money": False}
    return contract


def _coalesced(expr, read) -> bool:
    """True when ``read`` is the left operand of an ``or`` inside ``expr``
    (``row.get("k") or default``), so a null/absent value never reaches the column."""
    return any(isinstance(n, ast.BoolOp) and isinstance(n.op, ast.Or) and len(n.values) > 1
               and n.values[0] is read for n in ast.walk(expr))


def contract_errors(row: dict, contract: dict) -> list:
    errs = []
    for key, spec in contract.items():
        # absent == None for a .get read, so a non-null column needs the key too
        if (spec["required"] or not spec["nullable"]) and key not in row:
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
        want = _PYTYPES.get(spec["type"])
        if want is None:
            errs.append(f"unknown column type {key}")
            continue
        if isinstance(value, bool) and want is not bool or not isinstance(value, want):
            errs.append(f"wrong type {key}")
    return errs


def _contract(func, cls):
    return loader_contract(LOADER_SRC.read_text(encoding="utf-8"),
                           MODELS_SRC.read_text(encoding="utf-8"), func, cls)


def _rows(pack, name):
    path = PACKS / pack / "mini" / name
    assert path.is_file(), f"{pack}/mini/{name} is missing"
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


@pytest.mark.parametrize("func,pack,name,cls", FIXTURES)
def test_fixture_rows_match_the_loader_contract(func, pack, name, cls):
    rows = _rows(pack, name)
    assert rows, f"{pack}/mini/{name} has no rows"
    contract = _contract(func, cls)
    assert [(i, e) for i, r in enumerate(rows) for e in contract_errors(r, contract)] == []


@pytest.mark.parametrize("func,pack,name,cls", FIXTURES)
def test_fixture_is_labelled_synthetic(func, pack, name, cls):
    readme_path = PACKS / pack / "mini" / "README.md"
    assert readme_path.is_file(), f"{pack}/mini/README.md is missing"
    readme = readme_path.read_text(encoding="utf-8")
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


# --- nullability: derived from Optional[...] in models.py, not from row.get ---

@pytest.mark.parametrize("key,value,expected", [
    ("odometer_km", None, []),                      # Optional[int] column: null passes
    ("registration", None, []),                     # Optional[str] column: null passes
    ("vin_or_internal_id", None, ["null vin_or_internal_id"]),  # str column: null fails
    ("tenant_id", None, ["null tenant_id"]),        # scope key, str column: null fails
    ("availability_status", None, []),              # str column, loader coalesces `or "available"`
])
def test_fleet_null_follows_model_nullability(key, value, expected):
    row = {"tenant_id": "t", "estate_id": "e", "vin_or_internal_id": "SYNTH-1", key: value}
    assert contract_errors(row, _contract("load_fleet_mini", "FleetVehicle")) == expected


def test_intent_null_is_coalesced_by_the_loader():
    # every intents key is read as str(row.get(k) or default): null is safe
    assert contract_errors({"intent": None, "utterance": None},
                           _contract("load_hospitality_intents_mini", "HospitalityIntent")) == []


_LOADER = """
def load_x(session):
    for row in rows:
        session.add(V(a=row.get("a"), b=str(row.get("b") or "d"), c=row["c"]))
"""


@pytest.mark.parametrize("annotation,nullable", [
    ("Mapped[Optional[int]]", True),
    ("Mapped[int]", False),
])
def test_get_key_nullability_comes_from_the_model(annotation, nullable):
    models = f"class V:\n    a: {annotation}\n    b: Mapped[str]\n    c: Mapped[str]\n"
    spec = loader_contract(_LOADER, models, "load_x", "V")
    assert spec["a"]["nullable"] == nullable
    assert spec["a"]["required"] is False  # .get read: not a subscripted key
    # coalesced .get into a non-null column stays optional and null-safe
    assert spec["b"]["nullable"] is True
    # subscripted key into a non-null column: required and non-null
    assert (spec["c"]["nullable"], spec["c"]["required"]) == (False, True)


@pytest.mark.parametrize("row,expected", [
    ({"c": "x"}, []),
    ({"c": "x", "a": None}, []),
])
def test_optional_column_null_or_absent_passes(row, expected):
    models = "class V:\n    a: Mapped[Optional[int]]\n    b: Mapped[str]\n    c: Mapped[str]\n"
    assert contract_errors(row, loader_contract(_LOADER, models, "load_x", "V")) == expected


@pytest.mark.parametrize("row,expected", [
    ({"c": "x"}, ["missing required a"]),
    ({"c": "x", "a": None}, ["null a"]),
])
def test_non_null_column_null_or_absent_fails(row, expected):
    models = "class V:\n    a: Mapped[int]\n    b: Mapped[str]\n    c: Mapped[str]\n"
    assert contract_errors(row, loader_contract(_LOADER, models, "load_x", "V")) == expected
