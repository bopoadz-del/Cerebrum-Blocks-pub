all figures — pending interview, domain encoding sheet, Railway & Metro Construction.

No interview has run. Every `value` in `design_basis.yaml` is `null` and
stays null until it does. The qualifiers are present and enforced at load
time (TrackBasis, in reasoning.py); the values are not, and this layer
refuses rather than supplying a figure it does not have. The gate itself is
`manifest.yaml` + `invariants.yaml`, evaluated by app.blocks.kit_engine, and
never reads a value out of design_basis.yaml — it is provenance/interview
bookkeeping only.

Specifically outstanding:

- **All geometry limits per category** — plain_line, switches_and_crossings,
  bridge_approach, tunnel. Nothing interpolates between them, so each needs
  its own set; a limit filled for one category does not reduce the gap for
  another.
- **All SFT (stress-free temperature) records** — route, verification date,
  method and disturbed_since, per route and per line. Without all four an
  SFT figure cannot be quoted against any question.
- **Clearance / gauging assessments** — envelope_type, line_speed, cant and
  curve_radius are call-time qualifiers on top of the manifest figure; none
  are supplied yet.
- **TBM face pressure schedules** — chainage band (min AND max) and the
  ground/groundwater basis, per drive. Nothing is filled, so INV-5 refuses
  every face-pressure question.
- **Trigger levels** — the settlement/movement trigger per monitored
  building, from its own building risk assessment. Nothing carries between
  buildings.
- **Cost figures** — not supplied; out of scope beyond what the engineering
  supervisor or possession manager supplies.
- **Incident shapes** — the failure histories that would seed regression
  tests are not recorded.

## Not gaps

The refusals are not gaps. A question this layer refuses before retrieval —
can we hand the line back tonight, is it safe to work with adjacent line
open, can we put the crane here, can we stress the rail today, is this
building at risk, can we go into the four-foot — stays refused after the
interview. Those are named-person decisions and no manifest value changes
that.
