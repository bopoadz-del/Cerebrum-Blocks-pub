# Known gaps — fire protection & firefighting systems

all figures — pending interview, domain encoding sheet, Fire Protection.

No interview has run. Every `value` in `manifest.yaml` is `null` and stays null
until it does. The qualifiers are present and enforced at load time; the values
are not, and this layer refuses rather than supplying a figure it does not
have.

Also outstanding: **all classifications per building**. Hazard classification
is building- and space-specific — light hazard, ordinary hazard group 1/2,
extra hazard group 1/2 — and no classification has been made for any building
in scope. Nothing carries between buildings, so each needs its own
classification, its own engineer-of-record attribution and its own code
edition; a classification made for one building does not reduce the gap for
another.

Specifically outstanding:

- **All design densities per hazard classification and design-area basis** —
  light hazard, ordinary hazard 1/2, extra hazard, each under most_remote or
  most_demanding. Nothing carries between them; a figure filled for one
  classification or basis does not fill the others.
- **All fire-rated assembly listings** — the tested assembly, orientation and
  penetration detail for every rated wall, floor, shaft enclosure and door.
  Without the assembly listing, INV-5 refuses every rating question; the
  product data sheet alone is never proof.
- **Current flow test data** — no water-supply figure can be stated without a
  current flow test carrying a date and a location (REJECT_AS_PROOF: supply).
- **Impairment log and live system status** — both required for any coverage
  answer (INV-3); neither exists yet, so every coverage question refuses.
- **Code editions per building** — which edition of NFPA 13 / NFPA 14 / NFPA
  20 (or the applicable code) governs each building has not been recorded.
- **Cost figures** — not supplied; out of scope beyond what the fire
  protection engineer of record supplies.
- **Incident and impairment history** — the failure histories that would seed
  regression tests are not recorded.

## Not gaps

The refusals are not gaps. A question this layer refuses before retrieval —
what hazard class is this, is this building adequately protected, can we close
this valve, is a fire watch enough, can we occupy before testing, will this
pass, is this fire stopping OK — stays refused after the interview. Those are
named-person (engineer of record, AHJ, fire watch supervisor) decisions and no
manifest value changes that.
