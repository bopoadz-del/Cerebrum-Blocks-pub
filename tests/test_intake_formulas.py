"""The intake gate must refuse at the door.

Once a rate is in a shipped kit and an engine reads it, removing it is a
migration. Intake is the only point where refusing is cheap.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


intake_mod = _load("intake_formulas")


@pytest.fixture
def kit(tmp_path, monkeypatch):
    """A kit at a temp KITS_DIR, plus a candidate file to submit."""
    kits = tmp_path / "kits"
    (kits / "demo").mkdir(parents=True)
    (kits / "demo" / "manifest.json").write_text(
        json.dumps({
            "id": "demo", "name": "Demo", "version": "1.0.0", "description": "d",
            "status": "available", "blocks": ["alpha"], "data": [],
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(intake_mod, "KITS_DIR", str(kits))
    src = tmp_path / "rates.json"
    src.write_text(json.dumps({"rates": {"standard": 0.75}}), encoding="utf-8")
    return kits, src


def _manifest(kits):
    return json.loads((kits / "demo" / "manifest.json").read_text(encoding="utf-8"))


# -- no source, no encode -------------------------------------------------


def test_an_unknown_source_kind_is_refused(kit):
    kits, src = kit
    with pytest.raises(ValueError, match="unknown source kind"):
        intake_mod.intake("demo", str(src), kind="vibes", reference="x")


def test_a_checkable_kind_without_a_reference_is_refused(kit):
    """'regulator' with no citation is an assertion, not a source."""
    kits, src = kit
    with pytest.raises(ValueError, match="requires --reference"):
        intake_mod.intake("demo", str(src), kind="regulator", reference="  ")


def test_a_sourced_submission_is_encoded_and_declared(kit):
    kits, src = kit
    dest, declared, _ = intake_mod.intake(
        "demo", str(src), kind="regulator", reference="HKIA GN16 s3.2",
        today="2026-08-25",
    )
    assert declared is True
    body = json.loads(Path(dest).read_text(encoding="utf-8"))
    assert body["provenance"] == {
        "kind": "regulator",
        "recorded_on": "2026-08-25",
        "reference": "HKIA GN16 s3.2",
    }
    assert "app/data/rates.json" in _manifest(kits)["data"]


# -- parked, not labelled -------------------------------------------------


def test_unverified_figures_are_parked_outside_the_declared_data(kit):
    """The difference between parking a figure and labelling one: nothing
    loads it, because nothing is told it exists."""
    kits, src = kit
    dest, declared, messages = intake_mod.intake(
        "demo", str(src), kind="contributor_unverified", reference="sheet from D.",
    )
    assert declared is False
    assert "parked" in Path(dest).parts
    assert _manifest(kits)["data"] == [], (
        "an unverified submission was declared in the manifest, so an engine "
        "could load it"
    )
    assert "PARKED" in messages[0]


def test_a_parked_file_records_that_it_is_parked(kit):
    kits, src = kit
    dest, _, _ = intake_mod.intake(
        "demo", str(src), kind="contributor_unverified", reference="",
    )
    assert json.loads(Path(dest).read_text(encoding="utf-8"))["provenance"]["parked"] is True


def test_unverified_needs_no_reference(kit):
    """The point of the unverified tier is that it accepts what has none."""
    kits, src = kit
    _dest, declared, _ = intake_mod.intake(
        "demo", str(src), kind="contributor_unverified", reference="",
    )
    assert declared is False


# -- never silently replace a record --------------------------------------


def test_an_existing_provenance_record_is_not_overwritten(kit):
    kits, src = kit
    src.write_text(
        json.dumps({"provenance": {"kind": "spc", "reference": "line 4 run log"},
                    "rates": {"a": 1}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="already declares provenance"):
        intake_mod.intake("demo", str(src), kind="regulator", reference="something else")


def test_per_item_citations_survive_the_stamp(kit):
    """A submission that already cites per item keeps those citations."""
    kits, src = kit
    src.write_text(
        json.dumps({"rules": [{"id": "r1", "citation": "GN16 s1.2"}]}), encoding="utf-8"
    )
    dest, _, _ = intake_mod.intake(
        "demo", str(src), kind="regulator", reference="GN16", today="2026-08-25",
    )
    body = json.loads(Path(dest).read_text(encoding="utf-8"))
    assert body["rules"][0]["citation"] == "GN16 s1.2"
    assert body["provenance"]["kind"] == "regulator"


# -- misuse -------------------------------------------------------------


def test_an_unknown_kit_is_refused(kit):
    kits, src = kit
    with pytest.raises(ValueError, match="no kit at"):
        intake_mod.intake("nope", str(src), kind="regulator", reference="x")


def test_a_missing_file_is_refused(kit):
    kits, _src = kit
    with pytest.raises(ValueError, match="no such file"):
        intake_mod.intake("demo", str(kits / "absent.json"), kind="spc", reference="x")


def test_a_non_object_payload_is_refused(kit):
    kits, src = kit
    src.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        intake_mod.intake("demo", str(src), kind="spc", reference="run log")


def test_intake_is_idempotent_on_the_manifest(kit):
    kits, src = kit
    for _ in range(2):
        intake_mod.intake("demo", str(src), kind="spc", reference="run log")
    assert _manifest(kits)["data"].count("app/data/rates.json") == 1


# -- applied to the insurance kit ------------------------------------------

INSURANCE = REPO / "block_store" / "kits" / "insurance"
PARKED_INSURANCE = (
    "commission_formulas.json",
    "hierarchy_model.json",
    "incentive_playbook.json",
    "retention_playbook.json",
    "routing_sops.json",
    "sample_bordereaux.json",
)


def test_insurance_uncited_files_were_parked_through_intake():
    """The shipped rate table never went through the gate. Now it has.

    Six files had no source. The honest path is contributor_unverified,
    which parks them outside declared data. A regulator stamp we cannot
    check would have been worse than the blank.
    """
    parked = INSURANCE / "parked"
    manifest = json.loads((INSURANCE / "manifest.json").read_text(encoding="utf-8"))
    declared = set(manifest.get("data") or [])
    artifact_srcs = {item["src"] for item in manifest.get("artifacts") or []}

    for name in PARKED_INSURANCE:
        body = json.loads((parked / name).read_text(encoding="utf-8"))
        record = body["provenance"]
        assert record["kind"] == "contributor_unverified"
        assert record["parked"] is True
        assert record.get("reference"), "park records why it could not be sourced"
        assert "regulator" not in record["kind"]
        assert "HKIA" not in record.get("reference", "")
        assert "GN16" not in record.get("reference", "")
        rel = f"app/data/{name}"
        assert rel not in declared, f"{name} is still declared data; an engine can load it"
        assert rel not in artifact_srcs
        assert not (INSURANCE / "bundle" / "app" / "data" / name).exists(), (
            f"{name} is still in the shipped bundle"
        )


def test_insurance_gn16_ruleset_stays_shipped_on_its_own_citations():
    """The cited file is not parked. Per-rule HKIA cites already satisfy
    the composition audit; inventing a second file-level cite is not needed.
    """
    ruleset = INSURANCE / "bundle" / "app" / "data" / "gn16_ruleset.json"
    data = json.loads(ruleset.read_text(encoding="utf-8"))
    assert all(rule.get("citation") for rule in data["rules"])
    manifest = json.loads((INSURANCE / "manifest.json").read_text(encoding="utf-8"))
    assert "app/data/gn16_ruleset.json" in manifest["data"]
    assert not (INSURANCE / "parked" / "gn16_ruleset.json").exists()


def test_insurance_no_longer_ships_uncited_declared_data():
    """Parking closed the registered provenance gap. If a new uncited
    file lands in declared data, this fails before the audit is silenced.
    """
    spec = importlib.util.spec_from_file_location(
        "audit_kit_composition", REPO / "scripts" / "audit_kit_composition.py"
    )
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    known = audit._dirs(str(REPO / audit.REGISTRY_DIR)) | audit._modules(
        str(REPO / audit.MODULES_DIR)
    )
    findings = audit.audit_kit("insurance", str(REPO / audit.KITS_DIR), known)
    assert "data_provenance_missing" not in [code for code, _ in findings]


def test_known_incomplete_records_the_insurance_park():
    text = (REPO / "KNOWN_INCOMPLETE.md").read_text(encoding="utf-8")
    assert "block_store/kits/insurance/parked" in text
    assert "contributor_unverified" in text
    assert "EMBEDDED_FORMULAS" in text
    for name in PARKED_INSURANCE:
        assert name in text


def test_commission_engine_cannot_see_the_parked_rate_table():
    """Parking is a location, not a flag. The engine's hardcoded search
    path must not include parked/, and those default files must be gone.
    """
    src = (REPO / "app" / "blocks" / "agency_commission_engine.py").read_text(
        encoding="utf-8"
    )
    assert "kits/insurance/parked" not in src
    assert "EMBEDDED_FORMULAS" in src
    assert not (REPO / "app" / "data" / "commission_formulas.json").exists()
    assert not (
        INSURANCE / "bundle" / "app" / "data" / "commission_formulas.json"
    ).exists()
