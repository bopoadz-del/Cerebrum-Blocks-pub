all figures — pending interview, domain encoding sheet, Oil & Gas Operations.

No interview has run. Every `value` in `manifest.yaml` is `null` and stays null
until it does. The qualifiers are present and enforced at load time; the values
are not, and this layer refuses rather than supplying a figure it does not have.

Specifically outstanding:

- **All twelve figures** — MAWP, design pressure, operating pressure, high
  alarm, high-high trip, SOL, PSV set pressure, SIF setpoint, corrosion rate,
  flow rate, H2S concentration, worker exposure limit. Nothing carries between
  pressure_kind and envelope_tier, and nothing carries between assets, so a
  value filled for one tag does not reduce the gap for another.
- **Override, isolation and permit registers** — no protective-function (SCE)
  answer can be given until these are live, queryable sources; INV-3 refuses
  every SCE question until both an override_register_ref and an
  isolation_register_ref are supplied.
- **P&ID revisions and MOC references** — no figure cited from a P&ID or
  procedure can be dated until `P&ID_rev` and `MOC_ref` are populated; INV-5
  refuses in the meantime, and an unreachable document-control source is a
  refusal, not a stale-but-usable figure.
- **Inspection and calibration intervals** — corrosion CML data, PSV test
  intervals, SIF proof-test intervals, HAZOP/LOPA change history and gas
  detector calibration records are not recorded, so the staleness rules have
  nothing to compare a live claim against beyond the flags a caller supplies.
- **Cost figures** — not supplied; out of scope beyond what the operations
  supervisor or SCE owner supplies.
- **Incident shapes** — the failure histories that would seed regression tests
  are not recorded.

## Not gaps

The refusals are not gaps. A question this layer refuses before retrieval —
can we keep running with this, is it safe to break containment here, can we
bypass this trip, can we extend this inspection, is this vessel fit for
service — stays refused after the interview. Those are named-person decisions
(the operations supervisor, the SCE owner, the competent person) and no
manifest value changes that.
