"""{{name}} — reference domain block.

Generated from ``block_store/kits/_template/blocks/``. This is a working
block, not a stub: it runs, and the three tests beside it pass before you
change a line. Replace the body with the real work; keep the shape.

THE SHAPE, AND WHY IT IS THIS SHAPE
-----------------------------------
Every exit returns a :class:`~app.core.block_result.BlockResult`, and each
of the four statuses is reachable:

``refused``
    Nothing was supplied to work on, or the definition this block needs is
    not in the kit. Both are honest: the block has no source, so it does not
    answer. This is the exit that must NEVER be replaced by a confident
    number -- a kit that invents a total when its definitions are missing is
    the failure that still looks like an answer.

``partial``
    Some records could be handled and some could not. ``coverage`` says how
    many, ``reason`` names what was skipped. A partial answer presented as
    whole is the same failure wearing a different hat.

``failed``
    Something the block depends on broke. The reason says what.

``ok``
    Every record was handled against a definition the kit actually declares.

:meth:`known_fields` is deliberately a method rather than a constant. It is
the seam the mutation probe pulls on: remove the definition, and the block
must degrade visibly instead of guessing.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Set

from app.core.block_result import BlockResult
from app.core.contract_block import ContractBlock


class {{Domain}}Block(ContractBlock):
    """Summarise {{domain}} records against the kit's declared definitions."""

    name = "{{domain}}"
    version = "0.0.0-skeleton"
    description = "{{description}}"
    layer = 3
    tags = ["{{domain}}", "domain"]
    requires = []

    default_config = {
        # The field summed when the caller does not name one.
        "default_field": "amount",
    }

    def known_fields(self) -> Set[str]:
        """Fields this kit has a definition for.

        Replace with a read of the kit's own definition set (for example
        ``app/data/domain_definitions.json``). Returning an empty set is a
        legitimate state and the block handles it by refusing, never by
        falling back to arithmetic nobody declared.
        """
        return {"amount"}

    async def process(self, input_data: Any, params: Dict = None) -> BlockResult:
        params = params or {}
        data = input_data if isinstance(input_data, dict) else {}

        records = data.get("records")
        if not isinstance(records, list) or not records:
            return BlockResult.refused(
                "no {{domain}} records were supplied, so there is nothing to "
                "summarise"
            )

        field = data.get("field") or params.get("field") or self.config.get(
            "default_field"
        )

        # If the definition is not in the kit, say so. Do not sum anyway.
        fields = self.known_fields()
        if field not in fields:
            return BlockResult.refused(
                "this kit declares no definition for %r (it declares: %s), so "
                "the total it would produce would be the block's invention, "
                "not the kit's" % (field, ", ".join(sorted(fields)) or "nothing"),
                provenance=[
                    {
                        "derivation": "not_assessed",
                        "note": "no definition matched the requested field",
                    }
                ],
            )

        total = 0.0
        counted = 0
        skipped = []
        for index, record in enumerate(records):
            value = record.get(field) if isinstance(record, dict) else None
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                skipped.append(index)
                continue
            total += float(value)
            counted += 1

        provenance = [
            {
                "derivation": "grounded",
                "id": field,
                "source": {"kind": "kit_definition", "reference": "{{domain}} kit"},
            }
        ]
        payload = {"field": field, "total": total, "records": counted}

        if not counted:
            return BlockResult.refused(
                "not one of the %d record(s) carried a numeric %r"
                % (len(records), field),
                data={"field": field, "records": 0},
                coverage=0.0,
                provenance=provenance,
            )

        if skipped:
            return BlockResult.partial(
                "%d of %d record(s) carried no numeric %r and were left out of "
                "the total: rows %s"
                % (len(skipped), len(records), field, skipped),
                data=payload,
                coverage=counted / len(records),
                provenance=provenance,
            )

        return BlockResult.ok(
            payload, coverage=1.0, provenance=provenance
        )
