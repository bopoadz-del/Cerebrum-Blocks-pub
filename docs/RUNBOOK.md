# Cerebrum-Blocks — Store Runbook

One page for operating the block store. The store is inventory + execution
backend for the <private-repo> factory and for platforms it generates
(their REUSE capabilities call `POST /v1/execute` here at runtime). It is
not a standalone customer product.

## The live service (what actually runs)

- Render web service **`cerebrum-blocks`** (srv-d8rrorvavr4c73evhvi0),
  https://cerebrum-blocks.onrender.com — **Docker runtime** (`./Dockerfile`
  → `entrypoint.sh`), branch `main`, auto-deploy on push.
- Health check: `GET /ready` (503-capable: DATA_DIR writable + registry
  non-empty). `GET /health` is liveness-only and always 200 — never point
  monitoring at it.
- Persistent disk: 1 GB at `/app/data` (`DATA_DIR`) — API keys, rate-limit
  DB, uploads, backups. Losing it loses tenant keys.
- **`render.yaml` does NOT manage this service.** It describes the suspended
  `cerebrum-platform-api`. Env/config changes happen in the dashboard.
- Intentional absences on the store: `DATABASE_URL` unset (vector store /
  RAG off — RAG blocks are inventory shipped to platforms, not a store
  runtime feature); sandbox-runner pserv suspended (see below).

## When /ready returns 503

1. `data_dir` failing → disk full or unmounted: check the disk on the
   dashboard, `df` via SSH (`srv-…@ssh.oregon.render.com`).
2. `block_registry` failing → boot-time validation excluded everything:
   check boot logs for `app.blocks` validation warnings (signature or
   manifest failures — a bad manifest commit is the usual cause).
3. Stalled responses across the board: check for a wedged block execution;
   registry blocks run in worker threads with a 60 s subprocess timeout.

## Rollback

Render dashboard → the service → Deploys → previous successful deploy →
"Rollback". No migrations run on the store boot path, so rolling back the
image is complete. (The two SQL files in `migrations/` are CI-only.)

## Key rotation

- **Tenant API keys**: env vars `CEREBRUM_API_KEY_<NAME>` on the live
  service; add/remove in the dashboard, picked up within ~60 s. Revoke =
  delete the env var.
- **Master key** (`CEREBRUM_MASTER_KEY`): secrets block fails hard without
  it. Rotating it re-keys the secrets vault — coordinate with any stored
  secrets before rotating.
- **Publisher signing key**: `python scripts/rotate_publisher_key.py`
  re-signs all registry manifests and verifies 100% in one command; it
  writes the new private key OUTSIDE the repo. Commit the updated
  `data/publishers.json` + manifests, keep the private key in the
  operator's secrets manager.
- `KIMI_API_KEY`: dashboard env var; the only LLM credential.

## Backups / restore

- Nightly in-process snapshot of DATA_DIR (04:00 UTC, `BACKUP_KEEP=14`),
  report at `/v1/system/diagnostics` under `last_backup` (authenticated).
- Archives live on the same disk (`DATA_DIR/backups`) — they protect
  against logical loss, not disk loss. Copy archives off-host for that.
- Restore: `app/core/backup.py::restore_backup(archive, target_root)` —
  restores to an explicit target, never over the live location; verify,
  then promote deliberately.

## Sandbox runner

`cerebrum-sandbox-runner` (private service) is SUSPENDED. Platform-signed
(certified) blocks run in-process/subprocess and do not need it. Blocks
that resolve to community/reviewed-unsafe tiers require it and will 503
with "Sandbox runner unavailable" — resume the pserv and set
`SANDBOX_RUNNER_URL` before admitting third-party blocks.

## Alerting gap (owner action)

`notifyOnFail` covers failed deploys only. An external uptime check on
`/ready` is the minimum before anything customer-facing depends on this
service — a hung store cascades into the factory's `/ready` going red.
