# Cerebrum Agents (portable pack)

Vendor-neutral **Cerebrum** build-team agents for designing, implementing,
testing, documenting, and debugging blocks under the **Block Contract Layer**
(Pillar A — see `docs/CEREBRUM_V2_NORTH_STAR.md` §2).

## What this is

- Platform agents for Cerebrum itself — not Cursor, Kimi, Claude Code, or any IDE plugin.
- Plain markdown specs + a manifest. Any host may *load* them; none are required.
- Self-contained under `agents/` so the pack can move to other repos (aviation, FinanceOps, …).

## What this is not

- Not the run-time **Carry-Back Agent** (`docs/carry_back/`, `carry_back/`). That lives in the store and proposes migrations; these agents help *build* blocks.
- Not runtime Block Contract Layer code. Agents *enforce* the architecture when building; the `Block` base class / connection registry ship separately per north-star sequencing.

## Agents

| id | Role |
|----|------|
| `block-architect` | Design blocks with contracts + capabilities up front |
| `block-implementer` | Implement on the mandatory `Block` base class |
| `coder` | General implementation that still obeys BCL |
| `test-writer` | Contract tests (#4) + seam tests (#5) — keystone |
| `docs-writer` | Document contracts and connections |
| `chain-debugger` | Seam-first failure diagnosis |

Chain: `block-architect` → `block-implementer` / `coder` → `test-writer` → `docs-writer`. On failure → `chain-debugger`.

See [AGENTS_PORTABLE.md](./AGENTS_PORTABLE.md) and [MANIFEST.yaml](./MANIFEST.yaml).
