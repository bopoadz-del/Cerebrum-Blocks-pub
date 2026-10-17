# Marketplace Security Design (Track B)

## Goal

Make Cerebrum-Blocks safe for third-party publishers, like Google Play:
- Verified publishers can submit blocks.
- Buyers can install and run those blocks without trusting them with the whole platform.
- The store enforces isolation, validation, and audit by default.

## Threat model

A third-party block is assumed to be potentially malicious or buggy. It must not be able to:
- Read another publisher’s data or user sessions.
- Instantiate or call privileged blocks (`auth`, `secrets`, `database`, `billing`) unless explicitly declared and approved.
- Exfiltrate data over the network unless declared.
- Modify the platform or other blocks’ state.

## Four pillars

### 1. Publisher identity & code signing

Every published block must carry a verified identity.

- **Publisher registry**: `data/publishers.json` or DB table with `publisher_id`, name, contact, Ed25519 public key, trust tier (`verified`, `community`, `revoked`), created/revoked timestamps.
- **Block manifest**: `block.json` gains:
  - `publisher_id`
  - `signature` (base64 Ed25519 signature)
  - `digests` (SHA-256 of `block.json`, `block.py`, `requirements.txt`, `Dockerfile`)
- **Verification on install**:
  1. Look up publisher by `publisher_id`.
  2. Reject if revoked or missing.
  3. Recompute digests and verify signature against publisher public key.
  4. Only then copy into `block_registry/` or `app/blocks/`.

### 2. Memory isolation

`MemoryBlock` currently has one global `self.cache`. Change it to a namespaced store:

- Keys are stored under namespaces: `auth:`, `secrets:`, `block:{publisher_id}:{block_id}:`, `session:{session_id}:`.
- A block receives a **memory capability** that is bound to its namespace.
- `keys`, `get`, `set`, `delete`, `flush` cannot cross namespaces unless the caller holds an admin capability.
- Core blocks (`auth`, `secrets`) move to a private encrypted namespace backed by a separate SQLite file, not the shared memory cache.

### 3. Block validation gate

Before a block is registered, run a validation gate:

- **Static analysis**:
  - AST-based forbidden import check (`os`, `subprocess`, `socket`, `requests`, etc.) unless declared in manifest `permissions`.
  - Forbidden builtins (`eval`, `exec`, `compile`, `open`, `__import__`).
  - No access to `BLOCK_REGISTRY`, `block_instances`, `get_memory_block` unless declared.
- **Manifest checks**:
  - Required `publisher_id`, `signature`, `digests`, `permissions`.
  - `permissions` declares network, filesystem, block dependencies, and module imports.
- **Dynamic test run** (optional in MVP):
  - Run block tests inside the sandbox runner.
  - Require a smoke `process()` test and adapter `run()` test.
- **Certification**:
  - Store validation result under `block:{block_id}:certification`.
  - Blocks without a passing certification cannot be loaded into `BLOCK_REGISTRY`.

### 4. Sandboxing & capability proxy

Third-party blocks must not run in the main process by default.

- **Execution model**:
  - Core blocks (`auth`, `memory`, `monitoring`, `chat`, `pdf`, etc.) run inline.
  - Third-party blocks run via `block_registry/{id}/run.py` in a subprocess, or via the sandbox runner Docker container.
- **Capability proxy**:
  - Remove raw `BLOCK_REGISTRY`, `block_instances`, `_create_block_instance`, `get_memory_block` from `set_platform()`.
  - Pass a `PlatformCapabilities` object that exposes:
    - `get_dep(name)` — only declared `requires=[]` blocks.
    - `memory` — scoped namespace proxy.
    - `log_event(...)` — audit logging.
    - `request_permission(permission)` — explicit permission request.
- **Inter-block calls**:
  - A block can only call blocks listed in its manifest `requires`.
  - Calls are logged with caller/callee/args summary.

## MVP implementation plan

### Phase 1 — Publisher registry & signing (P0 of Track B)
1. `app/core/publisher_registry.py` — publisher CRUD + signature verification.
2. `scripts/sign_block.py` — CLI to sign a block folder with a publisher Ed25519 key.
3. `scripts/verify_block.py` — CLI to verify a block signature.
4. Update `block.json` schema to include `publisher_id`, `signature`, `digests`.
5. Update `scripts/audit_block_standards.py` to require signature for non-core blocks.

### Phase 2 — Memory namespace isolation
1. Refactor `app/blocks/memory.py` to support namespaced keys.
2. Add `MemoryNamespaceProxy` class for scoped access.
3. Update `app/dependencies.py` to give each block a scoped memory proxy instead of the global memory block.
4. Move `auth`/`secrets` keys to a private SQLite-backed namespace.

### Phase 3 — Validation gate
1. `app/core/block_validation.py` — AST-based static analysis + manifest checks.
2. `app/blocks/validation_pipeline.py` updated to use it.
3. Enforce validation before a block is added to `BLOCK_REGISTRY`.

### Phase 4 — Capability proxy & sandboxing
1. `app/core/platform_capabilities.py` — limited capability object.
2. Update `app/dependencies.py` `_wire_block_dependencies()` to pass only declared deps.
3. Remove or restrict `set_platform()` raw power.
4. Default third-party blocks to subprocess/Docker execution.

## Status

This document is the design baseline. Phase 1 implementation is next.
