all figures — pending interview, domain encoding sheet, Water Treatment Plant
Operations.

No interview has run. Every `value` in `design_basis.yaml` is `null` and stays
null until it does (unchanged — see below). `manifest.yaml` / `invariants.yaml`
are the additive, declarative kit_engine gate; they carry no figure values at
all, only the vocabulary and the rules, so there is nothing in them for an
interview to fill. The qualifiers/rules are present and enforced at load
time; the figure values are not, and both layers refuse rather than supply a
figure they do not have.

## Figure groups the manifest declares

- **ct_required / ct_achieved** — CT (disinfection credit), every
  temperature/pH row. CT_required and CT_achieved are read off the correct
  row of the CT table for the actual temperature and pH, not the nearest row
  and not an average. Without the table and the disinfectant/organism/
  log-target context, INV-WT-CT-QUALIFIERS refuses every CT question.
- **contact_time** — basis per basin. The clearwell tracer study (T10) and
  the rapid-mix theoretical detention are not interchangeable, and neither is
  supplied yet. Without the tracer study, INV-WT-CONTACT-BASIS refuses every
  contact-time question that needs its basis, and INV-WT-CURRENCY-CONTACTTIME
  refuses once a tank or baffle change has occurred.
- **chemical_dose** — delivered chemical strength, per delivery. The
  nameplate/rated strength on the drum is not the delivered strength; the
  delivered strength is supplied by the certificate of analysis on EACH
  delivery and is not recorded yet (staleness: chemical_strength — EACH
  delivery). INV-WT-DOSE-BASIS and INV-WT-CURRENCY-CHEMSTRENGTH refuse until
  it is.
- **turbidity_limit / chlorine_residual** — regulatory limits with averaging
  basis, monitoring frequency and named regulation. Not usable until all
  three are attached (INV-WT-LIMIT-QUALIFIER); a limit without them cannot be
  checked against a reading, and INV-WT-CONFLICT-REFUSE refuses rather than
  picks a winner when two sources disagree.
- **log_inactivation** — not carried in `design_basis.yaml` at all; pending
  interview in full, no prior gap entry to point to.
- **membrane_flux** — likewise not carried in `design_basis.yaml`; pending
  interview in full.

Engine-required plumbing — not sheet figures, declared only so the
manifest's own staleness_triggers can be governed (see manifest.yaml and
invariants.yaml INV-WT-CURRENCY-*). No interview value will ever fill these;
they track the currency of a live artifact, not a measured quantity:

- permit — the live discharge/abstraction permit
- chemical_strength — the certificate-of-analysis strength of the current
  delivery
- analyser — the online analyser's calibration state
- operating_manual — the current revision of the operating manual

## Also outstanding (unchanged from the design_basis.yaml layer)

- **Cost figures** — not supplied; out of scope beyond what plant operations
  supplies.
- **Incident shapes** — the failure histories that would seed regression
  tests (analyser calibration lapses, boil-notice triggers) are not recorded.

## Not gaps

The refusals are not gaps. A question this layer refuses before retrieval —
is this water safe to supply, can we skip filter-to-waste, do we need a boil
notice, can I enter the chlorine room — stays refused after the interview.
Those are named-person decisions and no manifest value changes that.

INV-WT-AUTH-LIMIT / the design_basis.yaml equivalent (conflicting limits from
two sources) is likewise not a gap the interview closes: a permit stricter
than the underlying code is a standing conflict to be reported, not resolved
by picking one source as authoritative.
