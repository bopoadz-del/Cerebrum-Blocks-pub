# The kit question sheets

Each `<kit>.md` here is the **domain owner's own question sheet**, verbatim: the
list of things that domain has to supply before a platform can gate its figures,
in the owner's words, with the owner's own mark on each.

These files are the record. `app/blocks/<kit>/questions.yaml` is a **generated**
view of them:

```
docs/kit_questions/<kit>.md          the record. Edit this.
        │
        │  scripts/import_kit_questions.py
        ▼
app/blocks/<kit>/questions.yaml      generated. Never hand-edit.
```

`tests/blocks/test_kit_interview.py` regenerates every file and fails if what is
committed differs, so the YAML cannot drift from the sheet. Without that guard the
YAML would be a second copy of the same fact, free to be quietly reworded — and a
hand-edit that turned a `[GATE]` question into a `[GAP]` would remove a gate with
nothing to catch it.

```
python scripts/import_kit_questions.py --check   # report, write nothing
python scripts/import_kit_questions.py           # write
```

## What the sheets carry that nothing else could

**`[GATE]` / `[GAP]`.** The owner's own split. A GATE question blocks: the platform
refuses anything needing it and names the question. A GAP question is experience
the platform is better for having and is never blocked without. Before the sheets,
every unanswered figure blocked equally, which would have held a build hostage to
*"what a PM new to fit-out most commonly gets wrong in their first year"*.

An **unmarked** question gates. The FM sheet marks nothing, and a question whose
class cannot be read must block rather than pass — the same fail-closed rule as the
rest of the layer. It is recorded as `gate: null`, so a reader can tell it was
unmarked rather than marked GATE.

**The answer format.** Each sheet opens with its own line:

| kit | fields every answer must arrive with |
|---|---|
| fitout, fm | unit, quality band, market, source, date, confirmed or indicative |
| fire_protection | unit, building/system, code edition, source, date |
| dental | unit, agent/item, adult or paediatric, protocol version, source, date |
| ports_marine | unit, asset/berth, source document, revision, date |

The platform kernel reads this rather than holding a list of its own, so there is
one definition of a complete answer per domain and it is the owner's. An answer
short of any field is refused, not stored partially: a cost without its market and
quality band is not an answer to *"cost per m² by quality band"*, it is a number
that will be cited as one.

**The real subject.** The derived question was *"What is the rate?"* — one number
for a whole domain, and unanswerable in practice. The sheet asks for the rate **per
package**: partitions, ceilings, raised floor, joinery, MEP, fire stopping, T&C,
prelims.

## Where answers go

Nowhere near here. A kit is a signed Store block shared by every customer; answers
are per-platform and live in the built platform's own storage
(`$STORAGE_PATH/reasoning_answers.json`), collected through
`GET`/`POST /v1/reasoning/interview`. A test asserts the kit directory is
byte-identical after an answer is recorded — one client's declared distances
reaching the next platform built from the same kit would be the provenance failure
this layer exists to prevent, and it would arrive signed.

## Coverage

15 of the 17 kits have a sheet, carrying **994 questions** — 647 `[GATE]`, 279
`[GAP]`, 68 unmarked (all of them FM's).

`datacentre` and `offshore_marine` have no sheet. **Neither is un-interviewed** —
see below.

## The other register: `design_basis.yaml`

Six kits were built with their own figure register before the question sheets
existed, and it is the better artefact by a distance. The figure names are the
domain's own — `lay_tension_min_kn`, `ups_autonomy_min_at_full_load`, not
`dimension` — each entry carries the qualifiers that figure is meaningless
without, and the file declares its own scope: *"spread- and vessel-specific, never
carry to another spread or sister vessel"*. `og_operations` calls its block
`operating_basis`, because that is what it is.

| kit | register | state |
|---|---|---|
| **datacentre** | `design_basis` | **17 of 18 answered**, facility_01. Open: `pue_guaranteed` |
| fire_protection | `design_basis` | declared, 11 open |
| offshore_marine | `design_basis` | declared, 11 open |
| og_operations | `operating_basis` | declared, 12 open |
| rail | `design_basis` | declared, 10 open |
| water_treatment | `design_basis` | declared, 9 open |

**Where a kit has a register, that IS its register** and nothing generates a second
one beside it. A generated per-quantity `figures:` block was written over all six,
and on the one whose register was *filled in* it reported 9 unanswered figures for a
facility that had answered 17 of 18 — an answered domain presented as an empty one,
while the real file sat in the same directory. The block is gone from those six,
`scripts/add_figure_questions.py` now skips them and says so, and a test per kit
fails if one comes back.

Four of the six (fire_protection, og_operations, rail, water_treatment) have **both**
a register and a sheet. They are not alternatives: the register holds *this asset's*
figures, the sheet asks *the organisation's* rules. Both have to be answered, and
`questions_source` reports `design_basis+owner_sheet`.

An empty register is not "nothing to ask" — it is everything still to ask. A kit
with neither a sheet nor a register reports `questions_source: derived` and is never
reported ready; adding an eighteenth kit with neither fails a test rather than
shipping quietly.
