"""bcf_export: the three tests + mutation probe required per block.

No BCF library is used anywhere here, on either side: export_bcf writes with
xml.etree.ElementTree and this suite reads back with the stdlib's zipfile
and ElementTree, so a round-trip failure can only mean this block's own
writer or validator is wrong -- never a third-party parser's opinion of BCF.
"""
from __future__ import annotations

import zipfile
from xml.etree import ElementTree as ET

import pytest

from app.blocks.geometry_engine import Finding
from app.blocks.bcf_export import export_bcf, validate_bcf_zip


def _clash_finding(a="DUCT-1", b="PIPE-2", **overrides):
    fields = dict(
        element_a=a, element_b=b, kind="clash", method="exact_boolean",
        distance_m=0.0, penetration_volume_m3=0.012,
        category_a="Duct", category_b="Pipe",
    )
    fields.update(overrides)
    return Finding(**fields)


def _clearance_finding(a="CABLETRAY-3", b="DUCT-4", **overrides):
    fields = dict(
        element_a=a, element_b=b, kind="clearance", method="min_distance",
        distance_m=0.18, required_clearance_m=0.30, rule_id="SBC-501-X",
        category_a="CableTray", category_b="Duct",
    )
    fields.update(overrides)
    return Finding(**fields)


def test_happy_export_produces_a_valid_bcf_zip_with_two_issues(tmp_path):
    """Two findings in, a real zip out: bcf.version at the root, one folder
    per issue, each with markup.bcf and viewpoint.bcfv, and the XML inside
    parses back to the Topic fields the finding actually carries."""
    findings = [_clash_finding(), _clearance_finding()]
    out = export_bcf(findings, tmp_path / "coordination.bcfzip", model_name="MEP-L3")

    assert out.exists()
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert "bcf.version" in names

        version_root = ET.fromstring(zf.read("bcf.version"))
        assert version_root.get("VersionId") == "2.1"

        issue_dirs = sorted({n.split("/", 1)[0] for n in names if "/" in n})
        assert len(issue_dirs) == 2

        seen_types = set()
        for folder in issue_dirs:
            assert f"{folder}/markup.bcf" in names
            assert f"{folder}/viewpoint.bcfv" in names

            markup = ET.fromstring(zf.read(f"{folder}/markup.bcf"))
            topic = markup.find("Topic")
            assert topic.get("Guid")  # non-empty, present
            assert topic.get("TopicStatus") == "Open"
            assert topic.find("Title").text
            assert topic.find("CreationDate").text
            seen_types.add(topic.get("TopicType"))

            viewpoint = ET.fromstring(zf.read(f"{folder}/viewpoint.bcfv"))
            components = viewpoint.find("Components/Selection")
            guids = {c.get("IfcGuid") for c in components.findall("Component")}
            assert guids == {"DUCT-1", "PIPE-2"} or guids == {"CABLETRAY-3", "DUCT-4"}

        assert seen_types == {"Clash", "Clearance"}


def test_clearance_findings_carry_clause_text_clash_findings_do_not_claim_one(tmp_path):
    """Planted failure, visible: a rule_id must actually show up as clause
    text in the Description, and a finding with no rule_id must not
    fabricate one -- a bug that dropped the clause or invented a citation
    would be caught right here."""
    clash = _clash_finding()
    clearance = _clearance_finding()
    out = export_bcf(
        [clash, clearance], tmp_path / "clauses.bcfzip", model_name="MEP-L3",
    )

    with zipfile.ZipFile(out) as zf:
        issue_dirs = sorted({n.split("/", 1)[0] for n in zf.namelist() if "/" in n})
        descriptions = {}
        for folder in issue_dirs:
            markup = ET.fromstring(zf.read(f"{folder}/markup.bcf"))
            topic = markup.find("Topic")
            descriptions[topic.get("TopicType")] = topic.find("Description").text

    # The clearance finding cites its rule -- the clause text must be present.
    assert "SBC-501-X" in descriptions["Clearance"]
    # And the measurement is still there alongside the clause.
    assert "0.18" in descriptions["Clearance"] or "0.1800" in descriptions["Clearance"]

    # The clash finding has no rule_id (geometry_engine's own contract: a
    # hard clash cites none) so it must not claim one anywhere.
    assert "Rule" not in descriptions["Clash"]
    assert "SBC" not in descriptions["Clash"]


def test_camera_omitted_without_centroid_present_when_centroid_given(tmp_path):
    """Refusing to invent a camera position is itself a behaviour worth
    locking down: no centroid -> no PerspectiveCamera element at all,
    rather than a fabricated (0,0,0) that would silently mislead a viewer."""
    no_centroid = _clash_finding()
    with_centroid = _clearance_finding()
    with_centroid.centroid = (12.5, 4.0, 3.25)  # duck-typed, optional attribute

    out = export_bcf(
        [no_centroid, with_centroid], tmp_path / "cameras.bcfzip", model_name="MEP-L3",
    )

    with zipfile.ZipFile(out) as zf:
        issue_dirs = sorted({n.split("/", 1)[0] for n in zf.namelist() if "/" in n})
        cameras_by_type = {}
        for folder in issue_dirs:
            markup = ET.fromstring(zf.read(f"{folder}/markup.bcf"))
            topic_type = markup.find("Topic").get("TopicType")
            viewpoint = ET.fromstring(zf.read(f"{folder}/viewpoint.bcfv"))
            cameras_by_type[topic_type] = viewpoint.find("PerspectiveCamera")

    assert cameras_by_type["Clash"] is None
    camera = cameras_by_type["Clearance"]
    assert camera is not None
    vp = camera.find("CameraViewPoint")
    assert float(vp.find("X").text) == pytest.approx(12.5)
    assert float(vp.find("Y").text) == pytest.approx(4.0)
    assert float(vp.find("Z").text) == pytest.approx(3.25)


def test_mutation_probe_validator_rejects_an_archive_missing_bcf_version(tmp_path):
    """Proves validate_bcf_zip is load-bearing, not decorative: build a zip
    that is missing bcf.version (the exact defect a broken writer could
    introduce by silently dropping that write) and confirm the validator
    this block ships -- the same one export_bcf calls on every write --
    actually rejects it rather than passing anything shaped like a zip."""
    broken = tmp_path / "broken.bcfzip"
    with zipfile.ZipFile(broken, "w") as zf:
        guid = "11111111-1111-1111-1111-111111111111"
        zf.writestr(f"{guid}/markup.bcf", b"<Markup/>")
        zf.writestr(f"{guid}/viewpoint.bcfv", b"<VisualizationInfo/>")
        # bcf.version deliberately omitted.

    with pytest.raises(ValueError, match="bcf.version"):
        validate_bcf_zip(broken)

    # And a real export from this block must never trip its own validator.
    good = export_bcf([_clash_finding()], tmp_path / "good.bcfzip", model_name="MEP-L3")
    validate_bcf_zip(good)  # no raise
