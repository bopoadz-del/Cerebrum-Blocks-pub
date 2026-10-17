"""Pytest configuration and fixtures."""

import pytest
import os
import sys
from pathlib import Path

# Add app to path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Activate dev mode for the test session so cb_dev_key is loaded.
# The auth module no longer auto-detects pytest via sys.modules (that
# was a security hole — see app/core/auth.py:_is_dev_environment).
# Tests that need an authenticated client must declare themselves
# tests via this env var.
os.environ.setdefault("ENV", "test")

# TestClient fires lifespan; without this every test app would arm the
# nightly backup scheduler and take a bootstrap snapshot into ./data.
# Scheduler tests opt back in explicitly with monkeypatch.
os.environ.setdefault("BACKUP_SCHEDULE_ENABLED", "0")

# Extended blocks are only registered when the platform boots in legacy mode.
os.environ.setdefault("CEREBRUM_VIRGIN", "false")

def _module_path(*parts: str) -> Path:
    """Where a module lives, whether it is a file or a package.

    app.containers.construction was refactored from construction.py into a
    construction/ package. This constant kept pointing at the .py file, so
    `.exists()` went False and two whole test files skipped themselves at
    module level -- tests/test_regression_construction.py and
    tests/test_xlsx_schedule.py, guarding the C1..C6 audit fixes. The kit was
    installed the entire time; only the probe was stale.
    """
    base = ROOT.joinpath(*parts)
    package_init = base / "__init__.py"
    return package_init if package_init.is_file() else base.with_suffix(".py")


CONSTRUCTION_CONTAINER_PATH = _module_path("app", "containers", "construction")
CONSTRUCTION_V2_PATH = _module_path("app", "blocks", "construction_v2")

requires_construction_kit = pytest.mark.skipif(
    not CONSTRUCTION_CONTAINER_PATH.exists(),
    reason=(
        "Construction kit not installed — run POST /store/containers/construction/install "
        "or copy from block_store/kits/construction/bundle/"
    ),
)

requires_construction_v2 = pytest.mark.skipif(
    not CONSTRUCTION_V2_PATH.exists(),
    reason=(
        "construction_v2 not installed — install construction kit from block_store "
        "or set CEREBRUM_DOMAIN_KITS=construction after install"
    ),
)

@pytest.fixture
def sample_text():
    return "Hello, this is a test document for Cerebrum Blocks."

@pytest.fixture
def sample_code():
    return """
def hello_world():
    print("Hello, World!")
    return 42

class MyClass:
    def __init__(self):
        self.value = 10
"""

@pytest.fixture
def data_dir():
    return "/app/data"
