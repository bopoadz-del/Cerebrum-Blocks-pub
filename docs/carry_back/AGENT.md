# Carry-Back Agent (operator guide)

**Lives in:** Cerebrum-Blocks (the store) — never in product repos.  
**Role:** Librarian, not author. **PROPOSES** store migrations; never silently mutates `main`.  
**Status:** `NOT LIVE` — modes `dry-run` / `propose` only until the LIVE gate clears.

North star: [CEREBRUM_V2_NORTH_STAR.md](../CEREBRUM_V2_NORTH_STAR.md) §4 (Pillar C).

---

## How to run

From the store repo root (with the repo on `PYTHONPATH` or cwd):

```bash
# Status / LIVE gate
python -m carry_back status

# Classify a seeded fixture or a product diff
python -m carry_back.seeds fixtures/carry_back   # seeded fixtures, generated (never committed)
python -m carry_back classify --fixture fixtures/carry_back/block_level_fix
python -m carry_back classify --diff path/to/product.patch

# Propose (writes under .carry_back/proposals/<id>/ only — not main tree blocks)
python -m carry_back propose --fixture fixtures/carry_back/block_level_fix --mode propose --open-pr
python -m carry_back propose --fixture fixtures/carry_back/platform_specific_fix --mode propose

# Acceptance self-test (both paths)
python -m carry_back self-test
```

Modes:

| Mode | Behaviour |
|------|-----------|
| `dry-run` | Classify + plan; write nothing |
| `propose` | Write proposal package + PR payload (gh create stays dry-run) |
| `live` | **Gated** — refused while `LIVE_ENABLED = False` |

---

## Acceptance (demonstrable)

1. **Block-level fixture** → proposal package contains:
   - migration diff (`migrate_<block>.diff`)
   - pinning regression test
   - seam-test **stub** (Pillar A hook)
   - fan-out report
   - ledger draft
   - PR payload (`pr_payload.json` / `pr_body.md`) for branch `carry-back/<id>`
2. **Platform-specific fixture** → decline; `DECLINED.md`; no migration proposal.
3. **No silent mutate** — store blocks on `main` are never patched by the agent; artifacts stay under `.carry_back/proposals/`.

Pytest: `pytest -q tests/carry_back/`

---

## LIVE gate

LIVE only after **both**:

1. One real (or acceptance) **block-level migrate** proposal demonstrated, and  
2. One **platform-specific decline** demonstrated correctly.

Then flip `LIVE_ENABLED` in `carry_back/__init__.py` and document the evidence in this file. Until then, report status as **NOT LIVE**.

Seam stubs are intentional: full Pillar A auto seam generation is out of scope for Carry-Back v0.

---

## GitHub Action stub

`.github/workflows/carry-back-propose.yml` — `workflow_dispatch` + optional `repository_dispatch` for later product webhooks. Does not auto-merge or push `main`.
