# Cerebrum V2 — North Star: The Self-Hardening Factory

**Author:** <owner> Mahmoud
**Status:** Design vision — build AFTER pilot ships. Not a pilot task.
**One-line thesis:** *A factory that learns from every platform it produces — because every fix lands in shared, contract-bound, self-testing blocks, so each platform ships more reliable than the last.*

---

## 0. Why this document exists

The pattern of building software has always been: **connect → run → find the bug → fix → repeat.** Blocks already made this *less messy* than traditional code, because a block is isolated — a bug lives inside one box and can't silently corrupt another. That was step one.

But the bugs did not disappear. **They moved from inside the components to the seams between them.** Every hard bug in the first production cycle was a *connection* bug, not a logic bug:

- Fork OAuth booted the user → a seam between **auth ↔ Drive/session** (broke only when the new UI landed; the block was fine for 3 months).
- "Answers from its ass" on an empty project → a seam between **retrieval ↔ synthesis**.
- Doubled blueprint text → a seam in the **SSE stream**.
- "Generated chain failed validation" → a seam between **generator ↔ validator**.

**Conclusion:** blocks are good. The next order of magnitude comes from making the *connections* impossible to get wrong. This document specifies how.

There are two kinds of seam, and they need different medicine:
- **Interior seams** (block ↔ block, same process): already isolated, already fast. Need contracts *without* network cost → **Block Contract Layer** (§2).
- **Edge seams** (platform ↔ outside world): unpredictable, the other side changes the rules. Need a standard, tested boundary → **MCP at the edges** (§3).

Same philosophy everywhere — *every connection carries an explicit, tested contract* — matched to the physics of each boundary.

---

## 1. The Thesis: The Compounding Loop

> **Fix at the edge, carry to the core, pin with a test — every platform hardens the store for the next.**

Traditional coding: a bug fixed in one app stays alive in every other app. You fix N times, or you get bitten N times.

Cerebrum model: the fix lands at the **block** — the single shared source every platform draws from — so one fix propagates everywhere the block lives. **Fix once, benefit everywhere.** This is why platform #3 (FinanceOps) took 2.5 hours when #1 took months: not faster typing — a smarter store with a shrinking bug surface.

This loop is currently run **manually, from memory**. V2's job is to make it **mechanical and permanent**, so it only ever tightens, never slips. Two mechanisms do that: the **Carry-Back Agent** (§4) automates the propagation, and **contract tests on every connection** (§2, pillar 5) make each fix un-regressable.

```
   ┌─────────────────────────────────────────────────────────────┐
   │                                                             │
   │   Platform N deployed ──► bug found at a seam ──► fixed     │
   │            │                                        │       │
   │            │                          "block-level truth?"  │
   │            │                                        │ yes   │
   │            │                                        ▼       │
   │            │                     Carry-Back Agent migrates  │
   │            │                     fix to STORE block +       │
   │            │                     writes regression test +   │
   │            │                     opens PR (<owner> approves)  │
   │            │                                        │       │
   │            ▼                                        ▼       │
   │   Platform N+1 inherits the hardened block — bug extinct    │
   │                                                             │
   └─────────────────────────────────────────────────────────────┘
              the ratchet: each turn tightens, never slips
```

---

## 2. Pillar A — The Block Contract Layer (interior seams)

**Not a new protocol. The enforcement layer FastAPI left optional.** FastAPI + Pydantic already give ~70% of what MCP's self-describing contracts provide; the missing 30% is making the contract **binding at the moment of connection** instead of advisory. That 30% is the whole win.

Built on the existing stack (FastAPI, Pydantic, SQLAlchemy) — nothing is thrown away. Five points; **all five required** — the fifth is the keystone that turns the other four from static safety into a self-hardening ratchet.

### Point 1 — Pydantic on BOTH sides of every block (strict)
Input validation probably exists already. The missed move: **validate OUTPUT too**, as an assertion at the block boundary. A block promising `{total: Decimal, currency: str}` must **fail loudly at itself** if it would emit anything else — so the bug surfaces at the *guilty* block, never at the innocent downstream block that trusted it. Nearly free; kills a whole class of seam bugs at their source.

### Point 2 — A mandatory `Block` base class
Enforce the pattern so no block can skip it. Every block inherits and declares:
- `InputModel` (Pydantic) — malformed input rejected at the door with a clear "rejected because Y", never a 500 five layers deep.
- `OutputModel` (Pydantic) — the block *guarantees* its output shape.
- `capabilities` descriptor — **the MCP-like piece**: the block announces what it *needs* and what it *provides*, in machine-readable form.
- a standard **error envelope** — every block fails the *same honest way*: `{block, status: "rejected"|"failed", reason, missing}`. Never a bare 500.

```python
class Block(ABC):
    InputModel:  type[BaseModel]
    OutputModel: type[BaseModel]
    capabilities: CapabilityDescriptor   # provides: [...], needs: [...]

    async def _run(self, data: InputModel) -> OutputModel: ...

    async def run(self, raw: dict) -> dict:
        try:
            data = self.InputModel.model_validate(raw)      # Point 1: input
        except ValidationError as e:
            return err(self, "rejected", reason=explain(e)) # honest envelope
        out = await self._run(data)
        return self.OutputModel.model_validate(out).model_dump()  # Point 1: output guaranteed
```
Write once; every block gets reliability by construction.

### Point 3 — A connection registry (design-time compatibility check)
Because every block now *declares* `provides`/`needs`, the factory verifies **at blueprint-assembly time** that block A's output satisfies block B's input — and **refuses to draft a platform with an incompatible seam.** This is the "USB plug that won't fit the wrong port." The pattern shifts:

> ~~connect → run → discover the seam broke → fix~~
> **connect → (rejected at connect if incompatible) → run works**

Bug discovery moves from **runtime** back to **assembly time**. This is only *possible* because of the descriptors from Point 2.

### Point 4 — Contract tests auto-GENERATED from the schemas
The contract is declared as data (the Pydantic models), so the **test that pins it can be generated**:
- per **block**: "does it honor its own input/output contract?"
- the declaration *is* the test source — no hand-written boilerplate.

### Point 5 — A test on EVERY CONNECTION *(the keystone — <owner>'s addition)*
Points 1–4 are static safety. **This** is what makes the compounding loop a ratchet.

For every **connection** in an assembled platform, auto-generate and run a **seam contract test**: *"block A, given realistic input, actually produces what block B actually consumes — end to end, across the real boundary."* Not a mock of A feeding B; the **real handoff exercised**, because a unit test passing while the live seam fails is the exact *wired ≠ works* trap that bit every bug above.

Why it's the keystone:
- Every connection ships with its **own guard** → a bad seam fails in **CI, not in your hands at 11pm**.
- When the Carry-Back Agent migrates a fix, it also (re)generates the **seam test that pins it** → the bug **cannot return** in the next platform. That is the mechanical closure of §1's loop.
- New, never-certified seams are the *only* place a surprise can still occur — and even then the kernel (§5) catches it before ship.

> **Points 1–4 make each block trustworthy. Point 5 makes each *connection* trustworthy, and makes every fix permanent. Without #5 the loop is a habit; with #5 it is a ratchet.**

---

## 3. Pillar B — MCP at the Edges (edge seams)

MCP is **AI-to-tool communication across a network** — a standard protocol for connecting to Drive, Slack, databases, third-party APIs. That is *exactly* the edge boundary that leaked (Drive being the poster child). Adopt MCP for **every platform ↔ world** connection:

- One standard contract for the Drive connection, the Slack connection, the next fifty integrations — instead of each a bespoke handshake debugged separately.
- MCP-native ⇒ plug into the whole exploding MCP ecosystem for free.
- Same protocol Anthropic and much of the industry are standardizing on ⇒ strategic alignment, not just engineering.

**Explicitly NOT for interior seams.** MCP is a *network* protocol (serialization, transport, round-trip) — the right cost to cross a trust boundary to the outside world, the *wrong* cost for two blocks in the same process passing data at memory speed. Interior seams get Pillar A (contracts without the network tax). **MCP ports on the outside of the box; typed pins on the inside.**

---

## 4. Pillar C — The Carry-Back Agent

The standing function that automates §1's loop so it survives tired hands. **Narrow, reactive, proposes-not-authors.**

**Trigger:** a bug is fixed at deployment on any platform.
**Job:**
1. Ask the one question: *platform-specific, or block-level truth?*
2. If block-level: migrate the fix to the **store block**, **write the regression test that pins it** (block-level, Point 4) **and regenerate the seam tests for connections that block participates in** (Point 5).
3. Check which other platforms use that block; flag which need the fix.
4. Open a **PR** — **<owner> approves**. The agent **never silently mutates the store** (the store is the crown jewels; a bad auto-migration poisons every future platform). *Librarian, not author.*
5. Maintain the **Extinction Ledger**: "bug class X, found on platform Y, now extinct across N platforms, pinned by tests T." This ledger *is* the compounding loop, made visible and auditable.

**Guardrails:** least-privilege; proposal-only; every migration carries its pinning test or it doesn't merge; scoped strictly to carry-back (never general "improve the blocks" latitude).

---

## 5. The Backstop — The Sweep Kernel (already built)

Even with Pillars A–C, a genuinely novel block combination can still produce a bad seam — that is the frontier, not a failure. The **certification kernel** catches it **before ship** and names **which seam**. So the worst case degrades from *"mysterious runtime bug in production"* to *"the kernel flagged connection X at build time."* ("Generated chain failed validation" was this backstop **working**.) Every platform leaves the factory with a **birth certificate** (health report + honest-limits + onboarding checklist).

---

## 6. How the pieces fit

```
        EDGE SEAMS                    INTERIOR SEAMS
   (platform ↔ world)            (block ↔ block, in-process)
   ────────────────────          ──────────────────────────────
        MCP ports                  Block Contract Layer (Pillar A)
   standard, networked            Pydantic in/out · Block base class
   Drive/Slack/APIs/DBs           connection registry · auto tests
                                   + SEAM TEST ON EVERY CONNECTION (#5)
              \                         /
               \                       /
                ▼                     ▼
            ┌───────────────────────────────┐
            │      ASSEMBLED PLATFORM        │
            └───────────────────────────────┘
                          │
            Sweep Kernel certifies before ship  ──► birth certificate
                          │
            Bug found in the field at a seam
                          │
            Carry-Back Agent (Pillar C): fix → store block
            + pinning test + seam test → PR → <owner> approves
                          │
                          ▼
            Next platform inherits it — bug extinct
                 (the ratchet turns, never slips)
```

---

## 7. Build order (AFTER pilot — this is not a pilot task)

1. **`Block` base class + strict Pydantic in/out (Points 1–2).** Foundation; migrate blocks onto it incrementally. First block migrated = first block that can never silently break its neighbor.
2. **Capability descriptors + connection registry (Point 3).** Unlocks design-time rejection of incompatible seams.
3. **Auto-generated block + seam contract tests (Points 4–5).** The keystone — turns the store into a ratchet.
4. **MCP edge adapters (Pillar B).** Drive first (it's the one that bit), then the integration catalog.
5. **Carry-Back Agent + Extinction Ledger (Pillar C).** Automates the loop once the tests it writes (3) exist to be written.

Sequencing rule: **1 → 2 → 3 before 5**, because the agent's whole value is writing the tests that only exist once the contract layer exists.

---

## 8. Why this is the moat (the Inception line)

Inception's Command Center *monitors* agents. **This factory gets structurally better every time it ships one** — because every fix lands in shared, contract-bound, self-testing blocks, and every connection carries a test that makes the fix permanent. That is a stronger story than anything on a competitor's product page, it is defensible (the Extinction Ledger is evidence), and it is already half-true today — the loop runs manually now. V2 just makes it mechanical.

> **The product isn't the platforms. The product is a factory that learns from every platform it builds — and never forgets a lesson, because the lesson lives in a test on a shared block.**

---
*Captured from a live brainstorm. Pattern, architecture, and reverse-engineering: <owner>. Blueprint: drafted with Claude. Build it in CerebrumDev's second phase — ship the pilot first.*
