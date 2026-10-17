# Known kit composition gaps

Registered findings from `scripts/audit_kit_composition.py`. A gap listed
here does not block CI. It is still a gap — registration makes it countable
and dated, not acceptable.

Format matches `KNOWN_INCOMPLETE.md`: `- <kit> :: <code>  <note>`.

## Why these are registered rather than fixed

Every domain kit below declares its blocks and says nothing about how they
compose. **Silence is not permission:** a kit that says its blocks are
independent has made a decision; a kit that says nothing has left an
omission, and only the author can tell the two apart.

What the code shows, so the gap is not overstated: these are **bundles, not
pipelines.** The 6-block domain kits ship pdf/ocr/chat/image alongside a
`<domain>_v2` block, and each generated container declares
`requires = ["<domain>_v2"]` and resolves exactly that one block. There is
very likely no ordering here to write down — the honest missing value is
`"flow": "independent"`, not a sequence.

They are registered rather than filled in because that judgement belongs to
the kit author. Asserting `independent` across seventeen kits on the
strength of their containers would be the same error as inventing a
sequence: a confident claim standing in for the author's decision. The
declaration is now available and the checker accepts it.

Two kits are not bundles and need a real answer:
`finance_ops` declares six finance blocks in `requires` and resolves them
by name, and `construction` (18 blocks) has no container under
`app/containers/` to read.

Registered 2026-08-24.

- agriculture :: no_composition  6 blocks; flow unauthored
- automotive :: no_composition  6 blocks; flow unauthored
- aviation :: no_composition  6 blocks; flow unauthored
- construction :: no_composition  18 blocks; largest kit, flow unauthored
- education :: no_composition  6 blocks; flow unauthored
- finance :: no_composition  6 blocks; flow unauthored
- finance_ops :: no_composition  11 blocks; flow unauthored
- hotel_management :: no_composition  6 blocks; flow unauthored
- hr :: no_composition  6 blocks; flow unauthored
- insurance :: no_composition  15 blocks; flow unauthored
- legal :: no_composition  6 blocks; flow unauthored
- manufacturing :: no_composition  6 blocks; flow unauthored
- medical :: no_composition  6 blocks; flow unauthored
- oil_gas :: no_composition  6 blocks; flow unauthored
- pharma :: no_composition  6 blocks; flow unauthored
- private_estate_operations :: no_composition  23 blocks; flow unauthored (moved from the Factory 2026-10-04; its workflows are declared under hats.workflows, not as a block flow)
- real_estate :: no_composition  6 blocks; flow unauthored
- retail :: no_composition  6 blocks; flow unauthored
- supply_chain :: no_composition  6 blocks; flow unauthored

## Provenance gaps

An encoded rate, threshold or limit with no recorded origin is not
"probably fine" — it is a number nobody can check. These files carry
figures whose source was never written down.

They are registered rather than filled in because **I cannot supply a
provenance I do not have.** Writing `"kind": "regulator"` above rates whose
origin is unknown would be worse than the blank: it would make an unchecked
number look checked, which is the exact failure this field exists to
prevent. Each needs its actual source recorded by whoever knows it.

`gn16_ruleset.json` is the worked example and is NOT registered: all 12 of
its rules carry a `citation` naming the HKIA GL16/GN16 section they came
from. `hkia_gn16_corpus.json` and `construction_kb.json` likewise cite per
entry.

Insurance's six uncited data files (commission_formulas, routing_sops,
retention_playbook, incentive_playbook, sample_bordereaux, hierarchy_model)
were parked 2026-08-29 via `scripts/intake_formulas.py --kind
contributor_unverified`. They are no longer declared data. The gap is
closed by parking, not by inventing a regulator cite.

Registered 2026-08-24.

- construction :: data_provenance_missing  app/data/procedures/procedures_db.json
- automotive :: data_provenance_missing  source_manifest.json
- private_estate_operations :: data_provenance_missing  fixtures/demo_estate.json (synthetic demonstration data, generated_by recorded; no SOURCE_KINDS entry describes synthetic fixtures)
- automotive :: data_file_missing  manifest declares "evaluation/", which is not on disk
