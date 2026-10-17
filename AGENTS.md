# AGENTS.md

## Cerebrum-Blocks is the Store

This repository is the block store (`block_registry/` + kit shelf). Generated
products are built by <private-repo> Factory. Do not re-implement Factory
pipelines here.

### Dual-registration

Every block used to generate a product must be registered in **both**:

1. Cerebrum-Blocks (`block_registry/` + kit shelf)
2. <private-repo> Factory shelf/registry (`backend/app/factory/block_registry/`
   or equivalent shelf consumer)

### Before creating a module

Grep this repo's `main` **and** sibling repos (<private-repo>, The_Fork)
before adding a new Python module. Consume the existing module, or dual-register
it with a drift test. Never re-implement a module that already exists under
another name.

Example: the credibility ladder is dual-registered (this repo's
`app/core/credibility.py` + <private-repo> `backend/app/core/credibility.py`)
with a shared literal pin. Do not invert one copy to match a bug in the other.

### Stage evidence never ships inside feature PRs

Do not commit Factory `build/stages/*.json` (or reread twins) in a feature PR.
Stage evidence is regenerable; emit it in a later single Factory run at final
HEAD after the code merge. Canonical S4 evidence is `S4_ship_kernel.json`
(`S4_kernel.json` is not a reader input).
