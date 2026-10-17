all figures — pending interview, domain encoding sheet, Dental.

No interview has run. The manifest and invariants declare the vocabulary and
the gates; no operating value is supplied for any quantity below, and none is
invented in its place — a gate with a value still absent still refuses.

Figure groups the manifest declares, against the interview sections the
domain encoding sheet gives for each (§1–§8):

- **anaesthetic_mrd** (maximum recommended dose) — §1, §1.7, §8.1, §8.5,
  §11.2, §11.6.3: dose qualifiers (agent, concentration, cartridge volume,
  vasoconstrictor, adult/paediatric), source specificity (edition or protocol
  version), mg/kg step visibility, and same-dose source conflict.
- **mg_per_cartridge** — §1, §8.1: same dose-qualifier chain as
  anaesthetic_mrd (same cartridge, different drug loads at different
  concentrations).
- **implant_torque** — §5.1: torque is system-specific and never carries
  between implant systems.
- **emergency_drug_dose** — no interview section is cited by an invariant
  yet; carries a staleness trigger (resuscitation_guideline_update) and is
  governed only by the blanket currency gate (INV-DEN-CURRENCY).
- **radiography_setting**, **drill_speed** — declared vocabulary only; no
  invariant or interview section cites either yet.
- **autoclave_hold_time**, **autoclave_temperature** — no interview section
  is cited; autoclave_hold_time carries a staleness trigger
  (validation_interval) and the blanket currency gate.
- **medical_history** — declared as an artifact quantity (not a measured
  figure), solely so its staleness trigger (visit_without_update) has
  something to be keyed on; governed by the blanket currency gate.

## Not gaps

The scope refusals — how much should I give this patient, is this patient fit
for treatment, can I treat despite this history/condition/contraindication,
what's causing this pain/symptom, is this radiograph normal — are
named-person clinical decisions (the treating clinician, the clinical
director, examination) and no interview answer changes that.
