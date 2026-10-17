#!/usr/bin/env python3
"""Console Floor pack — release gate.

A red suite must not produce a deployable image: this runs the pack's
contract + console tests. Non-zero exit fails the Docker build.
"""
import os
import subprocess
import sys

os.environ.setdefault("ENV", "test")
os.environ.setdefault("CEREBRUM_VIRGIN", "0")

print("[pack:console_floor] release gate: running contract + console tests")
result = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/packs/", "-q"],
    cwd="/app",
)
if result.returncode != 0:
    print("[pack:console_floor] RELEASE GATE FAILED — no deployable image")
sys.exit(result.returncode)
