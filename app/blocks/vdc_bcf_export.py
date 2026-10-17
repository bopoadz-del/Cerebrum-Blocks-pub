"""VDC BCF export. Markup XML inside a zip.

Donor: Cerebrum backend/app/vdc/bcf_export.py
Ported: camera offset, direction normalize, project.bcfp, bcf.version, markup.bcf.
Left behind: Clash class, PNG placeholder, BCFImporter.
Classification: verified_executable.
A snapshot is written only when the caller supplies bytes.
"""
from __future__ import annotations

import math
import zipfile
from pathlib import Path
from typing import Dict, List
from xml.etree import ElementTree as ET

from app.core.universal_base import UniversalBlock


def camera(center):
    pos = {"x": center[0] + 5.0, "y": center[1] + 5.0, "z": center[2] + 3.0}
    direction = {
        "x": center[0] - pos["x"],
        "y": center[1] - pos["y"],
        "z": center[2] - pos["z"],
    }
    length = math.sqrt(sum(v * v for v in direction.values()))
    if length > 0:
        direction = {k: v / length for k, v in direction.items()}
    return pos, direction, {"x": 0.0, "y": 0.0, "z": 1.0}


def markup_xml(topic):
    root = ET.Element("Markup")
    topic_el = ET.SubElement(root, "Topic", Guid=str(topic["id"]))
    ET.SubElement(topic_el, "Title").text = topic["title"]
    ET.SubElement(topic_el, "Description").text = topic["description"]
    ET.SubElement(topic_el, "Priority").text = topic.get("priority") or "normal"
    ET.SubElement(topic_el, "TopicType").text = "clash"
    return ET.tostring(root, encoding="unicode")


class VdcBcfExportBlock(UniversalBlock):
    """Write a BCF 2.1 zip from clash dicts."""

    name = "vdc_bcf_export"
    version = "1.0.0"
    classification = "verified_executable"
    requires = []
    layer = 2
    tags = ["vdc", "bim", "bcf"]
    default_config = {}
    ui_schema = {
        "input": {"type": "json"},
        "output": {"type": "json"},
        "params": [{"name": "action", "type": "select", "options": ["export"], "default": "export"}],
        "quick_actions": [],
    }

    async def process(self, input_data, params=None):
        data = input_data or {}
        action = (params or {}).get("action") or data.get("action") or "export"
        if action != "export":
            return {"status": "error", "error": "Unknown action: %s" % action}
        path = data.get("output_path")
        if not path:
            return {"status": "error", "error": "output_path required"}
        return self.export(data.get("clashes") or [], path, author=data.get("author") or "store")

    def export(self, clashes, output_path, author="store"):
        topics = []
        for clash in clashes:
            center = clash.get("intersection_center") or [0, 0, 0]
            if not isinstance(center, (list, tuple)) or len(center) != 3:
                return {"status": "error", "error": "intersection_center must be length 3"}
            pos, direction, up = camera([float(c) for c in center])
            title = clash.get("title") or "%s vs %s" % (clash.get("element_a"), clash.get("element_b"))
            description = clash.get("description") or "volume=%s penetration=%s" % (
                clash.get("intersection_volume"), clash.get("penetration_depth")
            )
            topics.append({
                "id": clash.get("id") or "%s|%s" % (clash.get("element_a"), clash.get("element_b")),
                "title": str(title),
                "description": str(description),
                "priority": clash.get("severity") or "normal",
                "camera_position": pos,
                "camera_direction": direction,
                "camera_up": up,
                "snapshot_png": clash.get("snapshot_png"),
            })
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        written_snapshot = False
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("project.bcfp", "<Project></Project>")
            zf.writestr("bcf.version", "<Version>2.1</Version>")
            for topic in topics:
                folder = str(topic["id"])
                zf.writestr(folder + "/markup.bcf", markup_xml(topic))
                vp = ET.Element("VisualizationInfo")
                cam = ET.SubElement(vp, "PerspectiveCamera")
                ET.SubElement(cam, "CameraViewPoint").text = str(topic["camera_position"])
                ET.SubElement(cam, "CameraDirection").text = str(topic["camera_direction"])
                ET.SubElement(cam, "CameraUpVector").text = str(topic["camera_up"])
                zf.writestr(folder + "/viewpoint.bcfv", ET.tostring(vp, encoding="unicode"))
                snap = topic["snapshot_png"]
                if isinstance(snap, (bytes, bytearray)) and snap:
                    zf.writestr(folder + "/snapshot.png", bytes(snap))
                    written_snapshot = True
        return {
            "status": "ok",
            "output_path": str(out),
            "topics": len(topics),
            "author": author,
            "snapshot_written": written_snapshot,
        }
