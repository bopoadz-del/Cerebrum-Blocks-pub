"""SafetyWorldDetectorBlock: judgment-free surfacing of what the model sees.

The block refuses honestly without SAFETY_WORLD_WEIGHTS, reports detections
(class/confidence/box) with the original prompt strings, and carries no
violation vocabulary — judgment stays with the operator.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.blocks.safety_world_detector import (
    SafetyWorldDetector,
    SafetyWorldDetectorBlock,
)


def _run(block, **data):
    return asyncio.run(block.process(dict(data), params={}))


def test_no_weights_env_refuses_honestly(monkeypatch, tmp_path):
    monkeypatch.delenv("SAFETY_WORLD_WEIGHTS", raising=False)
    image = tmp_path / "site.jpg"
    image.write_bytes(b"fake")
    block = SafetyWorldDetectorBlock()
    out = _run(block, file_path=str(image))
    assert "error" in out
    assert "SAFETY_WORLD_WEIGHTS" in out["error"]
    assert "detections" not in out


def test_missing_file_path_is_refused(monkeypatch):
    monkeypatch.delenv("SAFETY_WORLD_WEIGHTS", raising=False)
    block = SafetyWorldDetectorBlock()
    out = _run(block)
    assert out["error"] == "file_path required"


def test_unknown_action_is_named(monkeypatch):
    monkeypatch.delenv("SAFETY_WORLD_WEIGHTS", raising=False)
    block = SafetyWorldDetectorBlock()
    out = asyncio.run(
        block.process({"file_path": "x"}, params={"action": "label_violations"})
    )
    assert out["error"].startswith("Unknown action")
    assert out["available"] == ["detect"]


class _FakeDetector:
    class_names = ["high visibility vest", "person"]
    manifest = {"prompts": ["high visibility vest", "person"]}

    def detect(self, file_path: Path, conf_threshold: float = 0.25):
        return [
            {"class": "high visibility vest", "confidence": 0.81, "bbox": [1.0, 2.0, 3.0, 4.0]}
        ]


def test_detect_with_fake_engine_reports_sightings_not_judgments(tmp_path, monkeypatch):
    image = tmp_path / "site.jpg"
    image.write_bytes(b"fake")
    monkeypatch.setattr(
        "app.blocks.safety_world_detector.default_detector",
        lambda: _FakeDetector(),
    )
    monkeypatch.delenv("SAFETY_WORLD_WEIGHTS", raising=False)
    block = SafetyWorldDetectorBlock()
    out = _run(block, file_path=str(image), confidence=0.3)
    assert out["count"] == 1
    det = out["detections"][0]
    assert det["class"] == "high visibility vest"
    assert det["confidence"] == 0.81
    assert det["bbox"] == [1.0, 2.0, 3.0, 4.0]
    assert out["class_names"] == ["high visibility vest", "person"]
    # The block's output vocabulary must stay judgment-free.
    for key in out:
        assert "violat" not in key.lower() and "complian" not in key.lower() and "breach" not in key.lower()


def test_bad_confidence_value_is_refused(monkeypatch, tmp_path):
    monkeypatch.delenv("SAFETY_WORLD_WEIGHTS", raising=False)
    image = tmp_path / "site.jpg"
    image.write_bytes(b"fake")
    block = SafetyWorldDetectorBlock()
    out = _run(block, file_path=str(image), confidence="not-a-number")
    assert "error" in out
    assert "confidence must be a number" in out["error"]
