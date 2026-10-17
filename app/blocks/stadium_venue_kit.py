"""sports venue reasoning kit — store-facing block.

Identity only. Every rule this block enforces is DECLARED in
``app/blocks/stadium_venue/manifest.yaml`` (vocabulary) and ``invariants.yaml``
(records), and evaluated by the shared reasoning layer in
``app/blocks/kit_engine``. Nothing domain-specific lives in this file, which is
the point: forty-three hand-written gates is forty-three chances to order the
rules wrong, and one evaluator reading one declaration cannot.

The archetypes are why this is not "one stadium". A fixed championship venue, a
multi-tenant venue, a single-purpose venue and a TOURING event that is a guest in
someone else's building each mean something different by the same number, and
carrying a figure between them is the defect this kit exists to catch.

Values are NOT filled — no interview has run for this domain. The block reports
``interview_status`` and its figure register with every answer, and refuses rather
than supplying a figure it does not have.
"""
from __future__ import annotations

from app.blocks.kit_block import ReasoningKitBlock


class StadiumVenueKitBlock(ReasoningKitBlock):
    name = "stadium_venue_kit"
    kit_name = "stadium_venue"
    description = (
        "Declarative sports venue reasoning kit on the shared reasoning layer: eight "
        "invariant kinds (grounding, qualifier, unit_discipline, authority, "
        "provenance, currency, scope, derivation) plus band, across five hooks "
        "(H0 pre-retrieval, H1 ranking, H2 tool-time, H3 answer-time, H4 "
        "export-time). Covers event-day safety, licensed capacity, pitch envelope, "
        "broadcast lighting, rigging points and egress, across four venue "
        "archetypes including touring events. Scope refusals classify BEFORE "
        "retrieval: thirteen operational questions with named owners are refused "
        "without searching, because no document makes a go/no-go answerable. Fail "
        "closed: an unloadable kit refuses every statement rather than passing them "
        "through with no invariants. No interview has run, so every declared figure "
        "value is null and the block refuses rather than inventing one."
    )
    tags = ['stadium', 'sports_venue', 'events', 'crowd_safety', 'broadcast']

    async def process(self, input_data, params):
        """Route every statement through this kit's declared invariants.

        H0 first and alone when it refuses: a scope refusal must be returned
        BEFORE retrieval, so a caller that reaches only this hook never touches a
        corpus. H1-H4 then run the rest of the routing map, because a host that
        calls answer-time alone silently gets no authority or band coverage.
        """
        outcome = await self.run_kit(input_data, params)
        if outcome.get("status") == "success":
            outcome["detail"] = f"kit={self.kit_name} hooks={outcome['result']['hooks_run']}"
        return outcome
