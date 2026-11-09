"""Every advertised block the CLONER may attach must resolve to a runtime mapping.

The Factory CLONER parses ``app/blocks/__init__.py`` (it does not import it)
to find the module and class an adapter would call, and refuses by name when a
registry manifest has no runtime entry. program_engine shipped a signed
block.json and block code but no mapping and died in CLONER exactly like
formula_executor did before it. This test fails the Store gate if such a block
lands without its id -> (module, class) entry.
"""

from __future__ import annotations

import pytest

from app.blocks import _EXTENDED_BLOCK_DEFS, _GENERIC_BLOCK_DEFS


def _defs():
    return {**_GENERIC_BLOCK_DEFS, **_EXTENDED_BLOCK_DEFS}


@pytest.mark.parametrize(
    "bid,module,class_name",
    [
        ("program_engine", "app.blocks.program_engine.block", "ProgramEngineBlock"),
        ("project_reasoner", "app.blocks.project_reasoner", "ProjectReasonerBlock"),
    ],
)
def test_runtime_mapping_resolves_bid_to_module_and_class(bid, module, class_name):
    assert _defs().get(bid) == (module, class_name)
