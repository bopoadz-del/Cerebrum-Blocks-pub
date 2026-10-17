"""Root pytest configuration.

The ``cli/`` package and its copies under ``block_store/kits/`` contain pytest
modules that are designed to be executed from their own directory (they import
the ``cerebrum_cli`` package by relative path). Collecting them from the repo
root causes a package-name clash with the top-level ``tests/`` directory, so we
ignore all ``cli/tests`` directories during root collection. Run them with
``cd cli && python -m pytest tests/`` when needed.
"""

import os

# Match tests/conftest.py: extended blocks are registered in test sessions.
os.environ.setdefault("CEREBRUM_VIRGIN", "false")

collect_ignore_glob = [
    "cli/tests",
    "block_store/kits/_template/cli/tests",
    # The block template renders to tests/test_<domain>_block.py. Un-rendered,
    # its filename still holds the {{domain}} placeholder, which is not an
    # importable module name -- collecting it from the repo root is an error,
    # not a failing test. It is exercised by generating a kit from the
    # template: tests/core/test_template_three_tests.py.
    "block_store/kits/_template/tests",
    "block_store/kits/construction/bundle/cli/tests",
]
