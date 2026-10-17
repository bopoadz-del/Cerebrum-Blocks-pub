# KNOWN_GAPS — data centre reasoning layer (facility_01)

Not supplied by the domain encoding sheet. These are GAPS — nothing here is
filled in by the kit. The kit fails closed on every one of them.

- per-item lead times (§2 table blank)
- all cost figures (§3 blank — respondent stated IT-MW cost cannot be separated)
- L1–L5 proves/does-not-prove matrix per level (§4.1 blank, prose only)
- IST scenario acceptance criteria and durations per scenario (§5.1 blank)
- live-works permission matrix (§6.1 blank)
- authority matrix — who authorises what (§8.4 blank)
- rack density peak / high-density zone (not stated)

## Encoded regression case

The one real incident from the sheet is encoded as a test:

- chiller failure at IST; temperature rose faster than expected due to pump
  sequence time delay; corrected by re-modifying the control sequence.
- `tests/blocks/test_datacentre_reasoning.py::test_chiller_incident_pump_sequence_regression`
  asserts (1) the pre-correction IST result is stale after the control change
  and blocks, (2) the retested post-modification sequence is citable.

## Reference-pattern note

The task named `app/lib/construction_formulas.py` as the named-formulas
reference; that file does not exist in this repo. The actual reference
patterns used are `app/blocks/aviation_grounding_gate.py` (verdict gate) and
`app/reasoning_kernel/formulas.py` (named formulas with source attribution).
