# Store Trust-Tier Enforcement Design

**Date:** 2026-07-06  
**Repo:** Cerebrum-Blocks  
**Topic:** Enforce publisher trust tiers (`verified` / `community` / `revoked`) for block admission and execution on top of commit 61b465d9.

---

## 1. Goal

Make the existing publisher trust tiers in `PublisherRegistry` enforceable at runtime. After this change, the tier of a block's publisher directly determines how the block may execute.

## 2. Background

Commit 61b465d9 introduced:
- `BlockCapabilities` parsed from `block.json` `permissions`.
- `BlockValidator` (manifest, signature, digest, AST scan) with a JSON `CertificationStore`.
- `CapabilityProxy` that prevents unsafe blocks from running in-process.
- Execute-router dispatch to the sandbox runner for blocks with elevated capabilities.
- `PublisherRegistry` with tiers `verified`, `community`, `revoked`.

The missing piece is **tier enforcement**: `verified` and `community` currently behave identically, and `revoked` is only checked during signature verification.

## 3. Tier Rules

| Tier | Admission | Execution |
|---|---|---|
| `verified` | Allowed if validation passes | Capability-based dispatch: safe blocks run in-process; unsafe blocks run in sandbox runner |
| `community` | Allowed if validation passes | Always dispatched to sandbox runner, even if capabilities declare the block safe |
| `revoked` | Rejected; block is excluded from `BLOCK_REGISTRY` | N/A — block cannot be loaded |
| Unknown / missing certification | Treated as `community` | Always sandboxed |
| Core platform blocks | Trusted, no validation | Capability-based dispatch (unchanged) |

## 4. Components and Changes

### 4.1 `app/core/block_validation.py`

Add `publisher_tier: Optional[str]` to `BlockValidationResult`. During `validate_block()`:
- Look up the publisher in `PublisherRegistry`.
- If publisher is revoked, set `status="failed"` and add reason.
- Otherwise set `publisher_tier` to the publisher's tier or `"community"` if unknown.

### 4.2 `app/core/block_capabilities.py`

Add `publisher_tier: Optional[str] = None` to `BlockCapabilities`.

Add helper property:
```python
@property
def must_run_out_of_process(self) -> bool:
    return self.publisher_tier != "verified" or not self.is_safe_for_in_process
```

### 4.3 `app/blocks/__init__.py`

When building `_BLOCK_CAPS` for non-core blocks:
- Load the existing certification from `CertificationStore` if available.
- If certified, use `result.publisher_tier`.
- If not certified, look up the publisher directly in `PublisherRegistry`.
- If publisher is revoked, exclude the block.
- If publisher tier is unknown, default to `"community"`.

Attach the resolved tier to `BlockCapabilities`.

### 4.4 `app/routers/execute.py`

Replace the capability-only dispatch check with the tier-aware check:

```python
if capabilities.publisher_tier == "revoked":
    raise HTTPException(403, f"Block '{block_name}' is from a revoked publisher")

use_runner = capabilities.must_run_out_of_process
```

### 4.5 Tests

- `test_block_validation.py`: verify `publisher_tier` is recorded; verify revoked publisher fails validation.
- `test_block_capabilities.py`: verify `must_run_out_of_process` respects tier.
- `test_execute_dispatch.py`: verify `verified` safe block runs in-process, `community` safe block runs out-of-process, `revoked` block rejected.
- New integration test: load a block with a community publisher and assert it is dispatched to runner.

## 5. Error Handling

- Revoked publisher at boot: block excluded with log line.
- Revoked publisher at runtime (if block was already loaded before revocation): return HTTP 403.
- Unknown publisher: treated as community; no error, just sandboxed.
- Missing certification store: treat non-core blocks as community unless registry lookup says otherwise.

## 6. Scope Boundaries

- No changes to the sandbox runner itself.
- No changes to the capability model beyond adding tier awareness.
- No changes to publisher signing flow.
- No UI changes in <private-repo> (separate PR).
- No trust-tier scanner or revocation-list fetching (out of scope).

## 7. Success Criteria

- Full existing test suite passes (0 failures, 0 errors).
- New tests prove tier enforcement for `verified`, `community`, and `revoked`.
- A block from a `community` publisher with safe capabilities is dispatched to the sandbox runner.
- A block from a `revoked` publisher is rejected at admission and at runtime.
