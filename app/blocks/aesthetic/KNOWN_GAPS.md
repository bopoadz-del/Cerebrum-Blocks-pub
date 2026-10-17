all figures — pending interview, domain encoding sheet, Aesthetic Medicine.

No interview has run. The manifest and invariants declare the vocabulary and
the gates; no operating value is supplied for any quantity below, and none is
invented in its place. Unlike a single-site domain, the interview that would
supply a value runs PER CLINIC — brand, device fleet and protocol set differ
clinic to clinic — never once for the domain as a whole. A value filled for
one clinic does not reduce the gap for another.

Figure groups the manifest declares, against the domain-sheet interview
section each is drawn from:

- **neuromodulator_dose** — §1.1.1, §13: units are brand-specific and never
  equivalent without the brand named. §3.1, §8.3: dose qualifiers (brand,
  treatment area).
- **filler_volume** — §3.1, §8.3: dose qualifiers (brand, treatment area).
- **hyaluronidase_dose** — §1.2.1: reversal applies to HA product class
  only. §3.3, §8.3: indication (elective vs occlusion) and protocol version.
- **device_fluence**, **device_pulse_duration**, **device_cooling_temp** —
  §4.1, §8.3: device, skin type, treatment area and pass number, none of
  which is transferable between devices.
- **peel_contact_time** — no invariant sheet section is cited yet; carries a
  staleness trigger (product_change, pH_change) and is governed only by the
  blanket currency gate (INV-AES-CURRENCY).
- **anaesthetic_max_dose** — declared vocabulary only; no invariant or
  interview section cites it yet.
- **contraindication_list** — declared as an artifact quantity (not a
  measured figure), solely so its staleness trigger (guideline_update) has
  something to be keyed on; governed by the blanket currency gate.

## Not gaps

The scope refusals — how much should I inject, is this patient suitable, is
this swelling/redness/bruising/nodule normal, can I treat despite this
contraindication, what's causing this complication — are named-person
clinical decisions (treating practitioner, medical director, adverse event
protocol) and no per-clinic interview answer changes that.
