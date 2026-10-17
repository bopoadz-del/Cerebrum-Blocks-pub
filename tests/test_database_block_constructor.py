"""Every block must be constructible the way a generic caller constructs one.

``UniversalBlock.__init__`` declares ``(hal_block=None, config=None)``, and
every block in the roster follows it -- storage, team, workflow, dashboard,
capture. ``DatabaseBlock`` alone narrowed both to REQUIRED, so any caller
that builds blocks uniformly (``block_cls()``) worked on the whole roster
except one.

``workflow._run_pipeline`` is exactly such a caller. Measured on a booted
generated platform, a two-step pipeline whose first step writes a record:

    {"status": "partial", "results": [{"step_id": "step_0",
      "block": "database", "status": "failed",
      "error": "DatabaseBlock.__init__() missing 2 required positional
                arguments: 'hal_block' and 'config'"}]}

No workflow pipeline could ever include a database step.
"""

from __future__ import annotations

import inspect

import pytest

from app.blocks.database import DatabaseBlock
from app.core.universal_base import UniversalBlock

ROSTER = [
    "database", "storage", "team", "workflow", "dashboard", "capture",
]


def test_database_block_constructs_with_no_arguments():
    """The exact call workflow._run_pipeline makes."""
    block = DatabaseBlock()
    assert block.backend == "sqlite"
    assert block.connection_string.startswith("sqlite:///")
    assert block._connection is None


def test_config_is_still_honoured():
    block = DatabaseBlock(None, {"backend": "sqlite",
                                 "connection_string": "sqlite:///x.db"})
    assert block.connection_string == "sqlite:///x.db"


def test_an_explicit_none_config_is_not_an_attribute_error():
    assert DatabaseBlock(None, None).backend == "sqlite"


def test_no_block_narrows_the_base_constructor():
    """Whole-roster guard, so the next block cannot reintroduce this."""
    import importlib

    base = inspect.signature(UniversalBlock.__init__)
    base_required = {
        name for name, p in base.parameters.items()
        if name != "self" and p.default is p.empty
    }
    offenders = []
    for name in ROSTER:
        try:
            mod = importlib.import_module(f"app.blocks.{name}")
        except Exception:  # noqa: BLE001 — an unimportable block is another test's problem
            continue
        for attr in vars(mod).values():
            if (
                inspect.isclass(attr)
                and issubclass(attr, UniversalBlock)
                and attr is not UniversalBlock
                and "__init__" in vars(attr)
            ):
                required = {
                    pname for pname, p in inspect.signature(attr.__init__).parameters.items()
                    if pname != "self" and p.default is p.empty
                    and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
                }
                if required - base_required:
                    offenders.append(f"{name}.{attr.__name__}: {sorted(required)}")
    assert not offenders, (
        "block(s) require constructor arguments UniversalBlock does not: "
        + "; ".join(offenders)
    )


@pytest.mark.parametrize("name", ROSTER)
def test_every_block_in_the_roster_constructs_bare(name):
    import importlib

    try:
        mod = importlib.import_module(f"app.blocks.{name}")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"{name} not importable here: {exc}")
    classes = [
        a for a in vars(mod).values()
        if inspect.isclass(a) and issubclass(a, UniversalBlock)
        and a is not UniversalBlock and a.__module__ == mod.__name__
    ]
    if not classes:
        pytest.skip(f"{name} exposes no UniversalBlock subclass")
    for cls in classes:
        cls()  # must not raise TypeError
