# Console Floor pack — v1.0.0

The default console + boot floor for factory-emitted products.

## What it is

- **One UI** at `/` — a console that discovers capabilities from
  `GET /v1/capabilities` (no hardcoded capability names), drives the first
  two discovered capabilities, and shows the **authority label** every
  answer carries (`grounding.verdict` / `authority.verdict`).
- **Boot floor** — `alembic upgrade head` runs BEFORE uvicorn; a migration
  failure refuses boot. Storage lives on a mounted disk (`STORAGE_PATH`).
- **Release gate** — the image build runs `scripts/release_gate.py`; a red
  suite does not produce a deployable image.

## Environment variables (nothing is baked — no credentials in the pack)

| Variable | Default | Purpose |
|---|---|---|
| `STORAGE_PATH` | `/app/data` | Mounted-disk storage root; a product may override |
| `ENV` / `ENVIRONMENT` | `production` | `dev`/`test` relaxes API-key auth for local boots |
| `DATABASE_URL` | unset | Database for migrations + `/ready` |
| `CEREBRUM_MASTER_KEY` | unset | Secrets-block master key (token_urlsafe format) |
| `KIMI_API_KEY` | unset | LLM provider for chat/RAG paths; omitted → honest offline results |

The console has **no embedded token**: the operator pastes one, and it is
sent only as `Authorization: Bearer <token>` on API calls.

## Network posture P1

At runtime the pack initiates no outbound connections. Blocks declaring
network capability are refused by the store's capability gates unless the
product overrides policy. Build-time (pip, apt) is the only network phase.

## Floor, not a cage

A product may override **any** file in this pack — the pack is the starting
point, and the Factory's gates judge the result. Version and pin: this pack
is `console_floor@1.0.0`; a pilot records which pack version it shipped.

## Store catalog registration

- Registry file: `block_store/packs/console_floor/manifest.json`
  (schema `store_pack.v1`, type `pack`).
- Catalog route: `GET /v1/store/packs` lists registered packs.
- Factory follow-up: the Factory's store catalog currently renders
  blocks / connectors / kits. `pack` is a **new artifact type** — the
  Factory needs a follow-up change to display it.
