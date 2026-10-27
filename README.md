# The Store - Cerebrum Blocks 

Cerebrum Blocks is **The Store** of the Cerebrum platform: the certified,
MIT-licensed capability inventory that the CerebrumDev.ai Factory assembles
vertical platforms from. Blocks and kits are reached through one public API.

[![CI](https://github.com/bopoadz-del/Cerebrum-Blocks-pub/actions/workflows/ci.yml/badge.svg)](https://github.com/bopoadz-del/Cerebrum-Blocks-pub/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

> ### Part of the CEREBRUM ecosystem
>
> **The Store — Cerebrum-Blocks (this repo):** the certified capability
> inventory — typed execution blocks and domain kits, manifested and signed,
> reached through one API. Build a capability once; every sector inherits it.
> **The Factory — CerebrumDev.ai:** assembles Store blocks into governed,
> deployable vertical platforms, with evaluation gates in CI and release
> certification.
> **The Builds — cerebrum-builds:** the certified platform builds the Factory
> produces.
>
> **You are here: THE STORE** — the certified capability inventory every
> platform is assembled from.

---

## Why this exists

AI product teams keep rebuilding the same capabilities from scratch —
retrieval, agents, document processing, formula engines, vision — and then
rebuilding them again inside every vertical product. Cerebrum Blocks
turns those capabilities into **typed, reusable execution blocks** with a
uniform contract, so they are built once, certified once, and reused across
products, clients, and domain kits.

## What it is

| Component | Path | Purpose |
|---|---|---|
| Blocks | `app/blocks/` | typed execution modules (chat, RAG, documents, domain analysis, workbench, …) |
| Block runtime | `app/core/` | TypedBlock base with fail-closed I/O validation, trust-scope enforcement, grounding stage, capability model |
| Execute API | `app/routers/execute.py` | `/v1/execute` — auth, tier boundary, trust scope, grounding, capability dispatch |
| Block registry | `block_registry/` | manifest + adapter entries for discovery and subprocess execution |
| Store | `app/routers/store.py` + `block_store/` | Kit catalog, provenance-verified install, domain kits + the universal kernel |
| Sandbox runner | `sandbox-runner/` | Out-of-process execution service for blocks with elevated capabilities |
| Containers | `app/containers/` | Domain containers assembling blocks per vertical |

## Block categories

| Category | Examples (real block names) |
|---|---|
| **Reasoning / chat** | chat, agent_swarm, smart_orchestrator, adaptive_router |
| **Retrieval** | vector_search, knowledge, zvec |
| **Formulas** | formula_executor, formula_executor_v2, construction_advisor (cited construction KB) |
| **Documents** | pdf, ocr, xlsx_schedule, spec_analyzer, bim_extractor |
| **Domain analysis** | construction_v2, aviation_v2, finance_v2, medical_v2, … (domain verticals) |
| **Workbench** | workbench (bounded coding-agent CLI editing with diff + safety gates) |

## Unregistered material (COLLECTOR rung 2 — by design)

Some real block code deliberately has no registry entry yet. Registration
means "certified, versioned, signed" — these are candidate material the
COLLECTOR can survey and promote, not certified inventory:

- **Alias** (`document_engine_block`) — a path shim of the
  already-registered `document_engine` block (the package shadows the
  module); registering it would duplicate identity, not capability.
- **Library helpers** (`ifc_loader`, `_knowledge`, `_procedure_routing`) —
  shared modules consumed by registered blocks, not blocks themselves.

Newly registered in the close-out: estate blocks, `retail_v2`,
`safety_world_detector`, `mcp_adapter`, `inbound_webhook`, `workbench`.
All registry blocks are signed (publisher `cerebrum_platform`) and the
signing + manifest-contract gates run in CI.

## Domain kits

Domain kits ship under `block_store/kits/` (construction, aviation,
finance, medical, legal, retail, insurance, education, agriculture,
manufacturing, oil & gas, pharma, real estate, hotel management, HR,
supply chain, automotive, finance ops, mep coordination), plus the
`universal_kernel` capability kits. A kit is a manifest plus a bundle;
installs are provenance-verified (see Security model).

## Quick start

```bash
git clone https://github.com/bopoadz-del/Cerebrum-Blocks-pub.git
cd Cerebrum-Blocks-pub
pip install -r requirements.txt

# Required env (see .env.example):
export CEREBRUM_MASTER_KEY="$(python -c 'import secrets;print(secrets.token_urlsafe(32))')"  # secrets block fails hard without it
export KIMI_API_KEY="<moonshot key>"   # the platform's only LLM provider (chat/RAG/enhancer); omit and those paths return an honest offline/skip result

python -m pytest tests/integration -q   # verify
uvicorn app.main:app --reload           # serve on :8000  (GET /health -> {"status":"ok"})
```

## Execution modes

| Mode | When | Mechanism |
|---|---|---|
| in-process | blocks whose declared capabilities are safe | direct call inside the API worker |
| registry subprocess | registry-only blocks with safe capabilities | `block_registry/<id>/block.py` via subprocess |
| sandbox runner | blocks declaring network / filesystem / privileged imports | out-of-process `sandbox-runner/` service |

## Security model

- Every block declares capabilities (network, filesystem, privileged
  imports) in its registry manifest; elevated blocks are dispatched to the
  out-of-process sandbox runner, and revoked publishers cannot execute.
- `/v1/execute` enforces the tier block-access boundary, strips
  caller-supplied trust scope (tenant/permission keys are
  server-controlled), and routes answer-producing blocks through a
  mandatory grounding stage (blocked answers are null, verdicts audited).
- Kit installs verify a `provenance.json` (sha256 digests + root hash)
  when present; kits without one are labeled `absent — unverified` in the
  install response.
- Ed25519 block signing is **operating**: all `block_registry/*` manifests
  are signed by the `cerebrum_platform` publisher and verify at load
  (`scripts/verify_block.py`; the runtime admission gate in
  `app/core/block_validation.py` excludes a registry block whose signature
  fails). The publisher public key ships in `data/publishers.json`; the
  private key is held by the operator (rotate/re-sign with
  `scripts/rotate_publisher_key.py`, which writes the private key OUTSIDE the
  repo). A restricted primitive (`database`/`code`/`sandbox`/`secrets`/…) is
  additionally gated to unlimited-tier at block resolution, failing closed on
  an unauthenticated request.

## Docs

- [API.md](API.md) — the HTTP API surface
- [docs/STORE_INVENTORY.md](docs/STORE_INVENTORY.md) — the verified inventory (blocks, kits, vertical readiness, known defects)
- [REPO_STATUS.md](REPO_STATUS.md) — current inventory and status
- [SKILLS_BLOCK_LOGIC.md](SKILLS_BLOCK_LOGIC.md) — block logic notes
- [docs/decisions/phase1-dead-controls.md](docs/decisions/phase1-dead-controls.md) — control dispositions (wired vs deleted)
- [PARKED_BLOCKERS.md](PARKED_BLOCKERS.md) — honestly parked work (e.g. block signing)

## Inventory — verified, honest

The full verified enumeration (every block, every kit, per-vertical
readiness, and the known-defect list) lives in
**[docs/STORE_INVENTORY.md](docs/STORE_INVENTORY.md)** and is re-verified
against the files themselves, not memory. The short version:

- **Registry blocks** — all manifested and signed, verified by pattern
  sweep against the files themselves. The vertical `*_v2` domain blocks are
  registered and signed.
- **Kit directories** — the domain kits plus `universal_kernel` and
  `_template`, including the declared-ready verticals (hotels, insurance,
  construction, finance, retail, real estate, legal, mep coordination), each
  with real domain blocks beyond the generic core
  (`pdf, ocr, chat, image, formula_executor(_v2)`).
- **Excluded from testing** (no authoritative domain content): medical,
  veterinary, pharma.
- **Known defects are listed, not hidden** in the inventory file (for
  example `admin_block._preflight`'s database check).

Exact per-block and per-kit counts live in the generated inventory
([docs/STORE_INVENTORY.md](docs/STORE_INVENTORY.md)), re-verified against the
files, so they are not hand-maintained here.

## Contribute — build kits and blocks

This store is open for contributions. Every vertical kit and every block
is expected to follow the same standard, so a capability built once is
certified once and inherited by every sector.

**A block is:**

- `block_registry/<block_id>/block.json` — the manifest: `id`, `version`,
  `description` (what it *actually* does), `status`, `author`, `tags`,
  `blocks` (its dependencies), `core_modules`, `prompts`, `data`.
- `block_registry/<block_id>/block.py` — the execution adapter:
  `run(**kwargs) -> {"block_id", "status": "ok"|"error", "result", ...}`.
  `status: "error"` with `error`/`detail` is the only honest failure —
  never a silent ok.

**The rules:**

1. **No stubs.** A block that cannot fail is refused. Verifiers must
   verify (hash, compare, raise on mismatch — see
   `block_store/kits/universal_kernel/wave1/audit_evidence/` for the
   reference SHA-256 chain implementation). Gates must gate. Registries
   must persist. If you cannot implement it, do not publish it — leave it
   out and say so in the PR.
2. **Describe what it does, not what it should.** The manifest
   description is graded against the code in review.
3. **Fail-closed I/O.** Inputs are typed and validated; a malformed
   payload is `status: "error"`, never an exception-shaped surprise to
   the caller.
4. **A kit is a manifest plus a bundle**:
   `block_store/kits/<kit>/manifest.json` (id, name, version, description,
   `blocks` list, `core_modules`, `data`) and `bundle/` with the kit's own
   modules. Domain logic belongs in a `<vertical>_v2` block; the generic
   core (`pdf, ocr, chat, image, formula_executor*`) is shared and must
   not be forked per kit.
5. **Domain kits need domain content.** A vertical kit without a domain
   block is generic plumbing wearing a vertical name — the factory's
   inventory gate flags capabilities that resolve to no domain-relevant
   block. Build the `<vertical>_v2` block (schema, rules, domain
   knowledge) before claiming a new vertical is ready.
6. **Trust is earned, not asserted.** New blocks land as unverified until
   reviewed against the standard; the factory's declared-ready list moves
   only after a vertical's kit is real.

**Submit:** a PR against `main` with the manifest + adapter + a test that
proves the failure path (tamper detection fails, gates fail unmet
checklists, duplicates are rejected). See `block_registry/` for the
adapter shape and `block_store/kits/` for kit shape.

## License

MIT — see [LICENSE](LICENSE).
