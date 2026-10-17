# Medical & Healthcare Kit (draft)

Skeleton domain kit following the same layout as [`../construction`](../construction).

## Status

- **manifest status:** `draft` — listed in the block store but not installable until `artifacts` are populated and `bundle/` is published.
- **version:** `0.0.0-placeholder`

## Pattern (copied from construction)

| Piece | Construction (reference) | Medical (this kit) |
|-------|------------------------|--------------------|
| Manifest | `block_store/kits/construction/manifest.json` | `manifest.json` |
| Bundle | `bundle/app/{blocks,containers,core,...}` copied from Fork | `bundle/` — not created yet |
| Source repo | `bopoadz-del/The_Fork` | same (future medical sources) |
| Publish script | `scripts/publish_construction_kit.py` | TBD (`publish_medical_kit.py` or shared publisher) |
| Container class | `app.containers.construction.ConstructionContainer` | `app.containers.medical.MedicalContainer` (future) |
| Platform blocks | `pdf`, `ocr`, `image`, … | `pdf`, `ocr`, `chat` (platform) |
| Domain blocks | `construction_v2`, `boq_processor`, … | `medical_container` and others (future) |

## Manifest sections

1. **`source`** — where authoritative implementations live (Fork `main` today).
2. **`container`** — domain container class and default chat prompt once implemented.
3. **`blocks`** — block IDs registered when the kit is installed (platform blocks first).
4. **`prompts` / `data` / `core_modules`** — optional paths copied into `bundle/`.
5. **`artifacts`** — `{src, dest}` pairs; publish script copies `src` from Fork into `bundle/dest`.
6. **`install_requires`** — minimum platform version and Python constraint.

## Next steps

1. Add medical container and domain blocks to The Fork under `app/containers/medical.py` and `app/blocks/`.
2. Fill `artifacts` in `manifest.json` (mirror construction’s `{src, dest}` list).
3. Add `scripts/publish_medical_kit.py` (or extend the construction publisher).
4. Run publish locally or via CI; set `status` to `published` when `bundle/` is complete.
5. Enable kit install with `CEREBRUM_DOMAIN_KITS=medical`.

## CI note

Construction publishing is automated in [`.github/workflows/publish-construction-kit.yml`](../../../.github/workflows/publish-construction-kit.yml). A medical workflow can follow the same `workflow_dispatch` + artifact-upload pattern once sources exist in Fork.
