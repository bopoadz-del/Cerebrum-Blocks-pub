"""bcf_export: the ADVERTISED entry point, not the two module functions.

tests/blocks/test_bcf_export.py proves ``export_bcf`` and ``validate_bcf_zip``
write and reject real archives. It never constructs ``BcfExportBlock``, so the
class the registry advertises -- and the two refusals
``block_registry/bcf_export/block.json`` lists as acceptance criteria
(``unknown_action``, ``missing_arguments``) -- had no coverage at all.

Everything here goes through ``await BcfExportBlock().process(payload)`` and
then reads the archive that call produced back off disk with the stdlib's
zipfile + ElementTree. No assertion in this file is satisfied by an envelope
whose keys merely exist: each one names a string the writer had to compute
from the Finding it was handed, a file that had to appear on disk, or the
exact text of a refusal.
"""
from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from app.blocks.bcf_export import BcfExportBlock
from app.blocks.geometry_engine import Finding


def _clash_finding(**overrides):
    fields = dict(
        element_a="DUCT-1", element_b="PIPE-2", kind="clash",
        method="exact_boolean", distance_m=0.0,
        penetration_volume_m3=0.012,
        category_a="Duct", category_b="Pipe",
    )
    fields.update(overrides)
    return Finding(**fields)


def _clearance_finding(**overrides):
    fields = dict(
        element_a="CABLETRAY-3", element_b="DUCT-4", kind="clearance",
        method="min_distance", distance_m=0.18, required_clearance_m=0.30,
        rule_id="SBC-501-X", category_a="CableTray", category_b="Duct",
    )
    fields.update(overrides)
    return Finding(**fields)


def _topics(zf, names):
    """folder -> (title, description) for every issue in the archive."""
    out = {}
    for folder in sorted({n.split("/", 1)[0] for n in names if "/" in n}):
        topic = ET.fromstring(zf.read(f"{folder}/markup.bcf")).find("Topic")
        out[folder] = (topic.findtext("Title"), topic.findtext("Description"))
    return out


async def test_process_export_writes_the_archive_it_reports(tmp_path):
    """The envelope's result is a path that exists, and the file at that path
    carries the two findings' own measured numbers -- not a status word."""
    out = tmp_path / "coordination.bcfzip"

    env = await BcfExportBlock().process({
        "action": "export",
        "findings": [_clash_finding(), _clearance_finding()],
        "out_path": str(out),
        "model_name": "MEP-L3",
    })

    assert env["status"] == "ok"
    assert env["error"] is None
    assert Path(env["result"]) == out
    assert out.is_file()

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert ET.fromstring(zf.read("bcf.version")).get("VersionId") == "2.1"
        topics = _topics(zf, names)

    assert len(topics) == 2
    titles = {t for t, _ in topics.values()}
    descriptions = {d for _, d in topics.values()}

    assert "MEP-L3: Clash - DUCT-1 / PIPE-2" in titles
    assert "MEP-L3: Clearance - CABLETRAY-3 / DUCT-4" in titles

    # The measurement, formatted from the Finding this call was handed.
    assert (
        "Clash between DUCT-1 and PIPE-2: penetration volume 0.0120 m3 "
        "(method: exact_boolean)."
    ) in descriptions
    # A clearance topic must carry the clause it was judged against.
    clearance_desc = next(d for d in descriptions if "Clearance violation" in d)
    assert "measured separation 0.1800 m, required 0.3000 m" in clearance_desc
    assert "Rule SBC-501-X: minimum required clearance 0.300 m." in clearance_desc


async def test_process_export_drops_clear_and_unjudged_findings(tmp_path):
    """Only clash/clearance become topics. A 'clear' pair reaching a
    coordinator's issue list is the failure this filter exists to stop."""
    out = tmp_path / "filtered.bcfzip"

    env = await BcfExportBlock().process({
        "action": "export",
        "findings": [
            _clash_finding(),
            _clash_finding(element_a="A", element_b="B", kind="clear"),
            _clash_finding(element_a="C", element_b="D", kind="unjudged"),
        ],
        "out_path": str(out),
        "model_name": "MEP-L3",
    })

    assert env["status"] == "ok"
    with zipfile.ZipFile(out) as zf:
        topics = _topics(zf, zf.namelist())
    assert len(topics) == 1
    assert next(iter(topics.values()))[0] == "MEP-L3: Clash - DUCT-1 / PIPE-2"


async def test_process_export_points_the_camera_only_where_it_knows(tmp_path):
    """A centroid produces a real PerspectiveCamera at that point; a finding
    without one gets no camera rather than one aimed at (0, 0, 0)."""
    located = _clash_finding()
    located.centroid = (3.5, -1.25, 2.0)
    unlocated = _clearance_finding()

    out = tmp_path / "cameras.bcfzip"
    env = await BcfExportBlock().process({
        "action": "export",
        "findings": [located, unlocated],
        "out_path": str(out),
        "model_name": "MEP-L3",
    })
    assert env["status"] == "ok"

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        topics = _topics(zf, names)
        clash_folder = next(f for f, (t, _) in topics.items() if "Clash" in t)
        clearance_folder = next(f for f, (t, _) in topics.items() if "Clearance" in t)

        clash_vp = ET.fromstring(zf.read(f"{clash_folder}/viewpoint.bcfv"))
        clearance_vp = ET.fromstring(zf.read(f"{clearance_folder}/viewpoint.bcfv"))

    camera = clash_vp.find("PerspectiveCamera")
    assert camera is not None
    point = camera.find("CameraViewPoint")
    assert (
        float(point.findtext("X")),
        float(point.findtext("Y")),
        float(point.findtext("Z")),
    ) == (3.5, -1.25, 2.0)
    assert camera.findtext("FieldOfView") == "60.0"

    assert clearance_vp.find("PerspectiveCamera") is None
    # The viewpoint still selects both elements by GlobalId.
    selected = [
        c.get("IfcGuid")
        for c in clearance_vp.findall("./Components/Selection/Component")
    ]
    assert selected == ["CABLETRAY-3", "DUCT-4"]


async def test_process_validate_refuses_an_archive_missing_bcf_version(tmp_path):
    """validate must actually reject: a zip with an issue folder but no
    bcf.version comes back as the block's error envelope carrying the
    validator's own message."""
    broken = tmp_path / "broken.bcfzip"
    with zipfile.ZipFile(broken, "w") as zf:
        zf.writestr("2f0a/markup.bcf", b"<Markup />")

    env = await BcfExportBlock().process({"action": "validate", "path": str(broken)})

    assert env["status"] == "error"
    assert env["error"] == "invalid BCF archive: bcf.version is missing"
    assert env["detail"] == {"type": "ValueError"}
    assert env["result"] is None


async def test_process_validate_refuses_an_issue_folder_with_no_markup(tmp_path):
    good = tmp_path / "half.bcfzip"
    with zipfile.ZipFile(good, "w") as zf:
        zf.writestr("bcf.version", b'<Version VersionId="2.1" />')
        zf.writestr("7c31/viewpoint.bcfv", b"<VisualizationInfo />")

    env = await BcfExportBlock().process({"action": "validate", "path": str(good)})

    assert env["status"] == "error"
    assert env["error"] == "invalid BCF archive: 7c31 is missing markup.bcf"


async def test_process_validate_accepts_an_archive_this_block_wrote(tmp_path):
    out = tmp_path / "roundtrip.bcfzip"
    block = BcfExportBlock()
    written = await block.process({
        "action": "export",
        "findings": [_clearance_finding()],
        "out_path": str(out),
        "model_name": "L2",
    })
    assert written["status"] == "ok"

    env = await block.process({"action": "validate", "path": str(out)})
    assert env["status"] == "ok"
    assert env["error"] is None


async def test_process_refuses_an_unknown_action():
    """block.json acceptance criterion 'unknown_action': refused, not
    silently accepted."""
    env = await BcfExportBlock().process({"action": "purge"})

    assert env["status"] == "error"
    assert env["error"] == "unknown action: purge"
    assert env["detail"] == {"known": ["export", "validate"]}
    assert env["result"] is None


async def test_process_refuses_an_export_with_no_findings_and_writes_nothing(tmp_path):
    """block.json acceptance criterion 'missing_arguments': an incomplete
    export is refused, and -- the part that matters -- no file appears."""
    out = tmp_path / "never.bcfzip"

    env = await BcfExportBlock().process({"action": "export", "out_path": str(out)})

    assert env["status"] == "error"
    assert env["error"].startswith("missing or invalid arguments:")
    assert "findings" in env["error"]
    assert env["detail"]["required"] == [
        "findings", "out_path", "model_name", "viewpoints", "rule_lookup",
    ]
    assert not out.exists()


async def test_process_refuses_an_empty_payload_instead_of_exporting_nothing():
    """The default action is 'export'; an empty dict must not be read as a
    successful export of zero findings to nowhere."""
    env = await BcfExportBlock().process({})

    assert env["status"] == "error"
    assert env["error"].startswith("missing or invalid arguments:")
    assert env["detail"]["required"][0] == "findings"


async def test_process_refuses_a_non_dict_input():
    env = await BcfExportBlock().process("export everything please")

    assert env["status"] == "error"
    assert env["error"].startswith("missing or invalid arguments:")


async def test_execute_returns_the_process_envelope_unchanged(tmp_path):
    """execute() is the platform-facing name; it must not add, drop or
    rewrite anything process() decided."""
    out = tmp_path / "via_execute.bcfzip"
    payload = {
        "action": "export",
        "findings": [_clash_finding()],
        "out_path": str(out),
        "model_name": "MEP-L3",
    }
    env = await BcfExportBlock().execute(payload)

    assert env["block_id"] == "bcf_export"
    assert env["status"] == "ok"
    assert Path(env["result"]) == out
    with zipfile.ZipFile(out) as zf:
        assert ET.fromstring(zf.read("bcf.version")).get("VersionId") == "2.1"
