# AGENTS_PORTABLE — Cerebrum agent pack drop-in guide

**Pack:** `agents/` (Cerebrum build-team agents)  
**Vendor lock-in:** none. Not Cursor, Kimi, Claude Code, or any IDE. Hosts are optional adapters.

## What you are copying

| Path | Purpose |
|------|---------|
| `agents/*.md` | Six Cerebrum agent specs |
| `agents/MANIFEST.yaml` | ids, versions, chain, hand-offs |
| `agents/examples/` | Point-4 / Point-5 **test shape templates** |
| `agents/README.md` | Pack overview |
| `agents/AGENTS_PORTABLE.md` | This file |

Authoring hub today: **Cerebrum-Blocks** (the store). Some agents will move to other repos later — keep this pack self-contained.

## How to drop into another repo (aviation first)

1. Copy the entire `agents/` directory to the target repo root (or `git subtree add` / submodule).
2. Point your host (human, CI, IDE adapter) at `agents/MANIFEST.yaml` + the `.md` files. Do **not** rewrite source of truth into `.cursor/` or `.claude/` — optional generated wrappers only.
3. Adjust paths below to match the target repo layout.
4. Keep `examples/` — `test-writer` must match those shapes.

### Per-repo path adjustments

| Concern | Store (Cerebrum-Blocks) | Typical product (e.g. aviation) |
|---------|-------------------------|----------------------------------|
| Blocks | `app/blocks/`, `block_registry/` | `app/blocks/` (or kit install path) |
| Contract tests | `tests/contracts/` (recommended) | same convention under `tests/` |
| Seam tests | `tests/seams/` (recommended) | same |
| North star | `docs/CEREBRUM_V2_NORTH_STAR.md` | copy or link to store doc |

If a product has no `block_registry/`, map capability declarations to whatever registry the product uses — the **contract semantics** stay the same.

## Chain order

Happy path:

1. `block-architect` — design with contracts + seam list  
2. `block-implementer` **or** `coder` — implement on `Block` base  
3. `test-writer` — Point-4 contract tests **and** Point-5 seam tests  
4. `docs-writer` — document contracts + connections  

On any failure: **`chain-debugger`** first (seam / registry / Point-5 before internals).

```
block-architect → implementer|coder → test-writer → docs-writer
                         ↘              ↘
                          chain-debugger (seam-first)
```

## Distinct from Carry-Back

| | Cerebrum agents (this pack) | Carry-Back Agent |
|--|-----------------------------|------------------|
| When | Build / design time | Run-time maintenance |
| Where | Portable `agents/` pack | Store hub (`carry_back/`) |
| Job | Enforce Pillar A while building | Propose migrating fixes *into* store blocks |
| Mutates store? | Via normal PRs like any contributor | **Proposes only** (PR, never silent) |

Do not conflate. Carry-Back docs: `docs/carry_back/AGENT.md`.

## Pillar A (must remain in every agent)

1. Pydantic in **and** out  
2. Mandatory `Block` base + honest error envelope  
3. Connection registry (`provides` / `needs`)  
4. Auto contract tests from schemas  
5. **Seam test on every connection** (keystone — real A→B, no mock of A)

## Acceptance for a consuming repo

- Pack present under `agents/`  
- Host can invoke agents by id from `MANIFEST.yaml`  
- New blocks cannot merge without Point-4 + Point-5 coverage matching `agents/examples/`
