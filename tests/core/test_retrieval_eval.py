"""The retrieval eval harness runs and reports both sets.

Golden (corpus-sighted) has a floor; blind (corpus-blind) is a measurement —
its number is reported in KNOWN_LIMITATIONS.md, not asserted, so an honest
low score can never be silenced by a test edit.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_eval_harness_reports_both_numbers():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_retrieval_eval.py")],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=ROOT,
    )
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["golden"]["hit_at_k"] >= 0.9, "corpus-sighted retrieval regressed"
    assert 0.0 <= report["blind"]["hit_at_k"] <= 1.0
    assert report["blind"]["total"] == 12
