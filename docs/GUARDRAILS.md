# Guardrails — Cerebrum-Blocks

What this system is certified to do, what it is not certified to do, and
which integrations are mock or stub. Modeled on the pilot-guardrails
standard used in The Fork.

## Certified for

- **Typed block execution with fail-closed validation.** A block whose
  output violates its declared schema returns an error envelope — never a
  silent success.
- **Trust-scope enforcement on `/v1/execute`.** Caller-supplied
  tenant/user/permission scope is stripped and replaced with the
  server-derived scope from the validated API key; every strip is disclosed
  in response metadata.
- **Tier boundaries.** Free keys reach only their allowed block set; rate
  limits (20/min free) and monthly usage caps are enforced per key.
- **Grounded answers on the chat/knowledge/aviation paths.** Verdicts
  grounded / flag-as-estimate / blocked; blocked answers are null; every
  verdict is persisted to an append-only audit log.
- **Provenance-verified kit installs** when a `provenance.json` manifest is
  present; tampered kits are refused.
- **Cited construction guidance.** `construction_advisor` returns KB entries
  with provenance and credibility tiers, and validates procurement workflow
  transitions through an AST-allowlisted guard evaluator.
- **Signed registry blocks.** All 105 `block_registry` blocks carry
  verifying Ed25519 signatures, enforced at load time; the private key is
  held in the owner's secrets manager, never in the repo.
- **Scope refusal.** Questions in the refusal categories (medication
  dosing, structural sign-off, legal filing strategy, live emergency) are
  never attempted, however grounded the corpus.
- **Tenant isolation on stateful blocks.** Storage namespaces are
  server-derived from the API key; a caller cannot name another tenant's
  namespace (covered by a concurrent two-tenant test).

## Not certified for

- **Corpus-blind domain Q&A.** Blind retrieval hit@5 is 0.25 — see
  KNOWN_LIMITATIONS.md. Do not present KB retrieval as domain expertise.
- **Professional advice.** Domain analysis blocks (medical, legal, finance,
  aviation, …) produce structured analysis over supplied inputs; none is
  certified for unsupervised professional judgement.
- **Semantic retrieval quality in offline environments** (embedder
  fallback is lexical and cross-call incomparable).
- **Signed kit *bundles*.** Registry blocks are signed, but domain-kit
  bundles are provenance-verified (sha256) rather than Ed25519-signed;
  kits without a `provenance.json` install labeled `absent — unverified`.
- **Unattended multi-tenant production isolation beyond the enforced
  boundaries above.** Tenant isolation on stateful blocks is enforced;
  project-level isolation *inside* a tenant is not yet.

## Mock / stub inventory (in-product labels)

| Surface | State | Label a caller sees |
| --- | --- | --- |
| `android_drive` | not implemented | `error: not_implemented` |
| `agent_swarm` with no agents/tasks | demo output | `mode: "demo"` + note |
| `bim_extractor` without an IFC file | demo output | `mode: "demo"` + note |
| `capture` without an image | demo output | `mode: "demo"` + note |
| Kimi workbench without the CLI | inoperative | `/health` `kimi_workbench.cli_ok: false` |
| Kits without provenance manifests | unverified | install response `provenance: "absent — unverified"` |

Anything discovered claiming more than this document allows is a bug —
file it as such.
