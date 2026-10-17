all figures — pending interview, domain encoding sheet, Oil & Gas Construction.

Per figure group the manifest declares (no interview IDs given on the sheet
excerpt encoded here):

- pressure / test_pressure — design, MAWP, hydro, pneumatic, leak and
  operating pressures, and the medium and lowest-rated component a test is
  qualified against
- pneumatic_radius — exclusion radius for a pneumatic test
- preheat_temp / pwht_temp / pwht_hold_time — welding heat-treatment figures
- zone_classification — hazardous-area classification, tied to the HAC
  revision it was struck against
- gas_free_level / oxygen_level / h2s_level — atmospheric test figures
- ndt_extent — non-destructive examination coverage
- isolation_boundary — the live isolation boundary (never the isolation plan)

Engine-required plumbing — not sheet figures, declared only so the
manifest's own staleness_triggers can be governed (see manifest.yaml and
invariants.yaml INV-OGC-CURRENCY-*). No interview value will ever fill
these; they track the currency of a live artifact, not a measured quantity:

- gas_free — live gas-test state
- HAC — hazardous-area-classification package revision
- pid — as-built P&ID revision
- isolation — live isolation certificate state
- WPS — welding-procedure-specification continuity/revision
