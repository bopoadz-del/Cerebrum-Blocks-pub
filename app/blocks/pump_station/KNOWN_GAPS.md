all figures — pending interview, domain encoding sheet, Pump Station.

Per figure group the manifest declares (no interview IDs given on the sheet
excerpt encoded here):

- npsh_required / npsh_available / npsh_margin — NPSHr (3% head-drop value)
  and NPSHa, and the required margin that must travel with them
- por_flow_min / por_flow_max / aor_flow_min / aor_flow_max /
  min_continuous_flow — the operating envelope, with POR/AOR named and what
  authorises operation in AOR
- max_discharge_pressure / surge_pressure — discharge and surge figures, for
  THIS impeller trim
- min_submergence — anti-vortex submergence
- starts_per_hour — duty-cycle limit
- vibration_trip — protection setpoint, with whether protection is currently
  in service
- h2s_evac_level — evacuation trigger level

Engine-required plumbing — not sheet figures, declared only so the
manifest's own staleness_triggers can be governed (see manifest.yaml and
invariants.yaml INV-PS-CURRENCY-*). No interview value will ever fill these;
they track the currency of a live artifact or study, not a measured
quantity:

- pump_curve — manufacturer curve for the installed trim
- surge_study — the network surge study
- npsha — the process conditions NPSHa was computed from
- protection_setpoints — the SCADA-held trip setpoints
- efficiency — the last-tested efficiency
- wet_well_volume — the last-surveyed wet well volume
