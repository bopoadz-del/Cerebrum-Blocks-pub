"""Make neutral_platform/ importable and point tests at an isolated DB."""

from __future__ import annotations

import os
import secrets
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# generated per test run, never a fixed value
os.environ.setdefault("NEUTRAL_AUTH_SECRET", secrets.token_hex(32))
# Each pytest process gets its own sqlite file unless CI sets NEUTRAL_DB_URL.
if not os.environ.get("NEUTRAL_DB_URL"):
    _db = Path(tempfile.gettempdir()) / f"neutral_platform_test_{os.getpid()}.db"
    os.environ["NEUTRAL_DB_URL"] = f"sqlite:///{_db}"
