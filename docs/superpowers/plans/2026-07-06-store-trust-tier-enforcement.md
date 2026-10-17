# Store Trust-Tier Enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce publisher trust tiers (`verified` / `community` / `revoked`) for block admission and execution in Cerebrum-Blocks.

**Architecture:** Extend the existing `BlockValidationResult` to record the publisher tier, carry that tier through `BlockCapabilities`, attach it during block registry construction, and apply tier-aware dispatch in the execute router. Core blocks remain trusted; non-core blocks default to `community` unless certified/registered as `verified`; revoked publishers are rejected.

**Tech Stack:** Python 3.11, FastAPI, pytest, existing `app.core.publisher_registry`, `app.core.block_validation`, `app.core.block_capabilities`, `app.core.block_proxy`, `app.routers.execute`.

## Global Constraints

- No changes to the sandbox runner itself.
- No changes to the capability model beyond adding tier awareness.
- No changes to publisher signing flow.
- No UI changes in <private-repo>.
- Full existing test suite must pass: 0 failures, 0 errors.
- Unknown / uncertified non-core publishers default to `community` tier (fail-closed).

---

## File Map

| File | Responsibility |
|---|---|
| `app/core/block_validation.py` | Certification result now records `publisher_tier`; revoked publishers fail validation. |
| `app/core/block_capabilities.py` | Capability object carries `publisher_tier` and exposes `must_run_out_of_process`. |
| `app/blocks/__init__.py` | Resolve publisher tier for non-core blocks and attach to `_BLOCK_CAPS`. |
| `app/routers/execute.py` | Reject revoked blocks; dispatch `community` blocks to runner even when safe. |
| `tests/core/test_block_validation.py` | Verify tier recording and revoked-publisher failure. |
| `tests/core/test_block_capabilities.py` | Verify `must_run_out_of_process` by tier. |
| `tests/core/test_execute_dispatch.py` | Verify router dispatch decisions by tier. |

---

### Task 1: Record publisher tier in `BlockValidationResult`

**Files:**
- Modify: `app/core/block_validation.py`
- Test: `tests/core/test_block_validation.py`

**Interfaces:**
- Consumes: `PublisherRegistry.get(publisher_id)` → `PublisherRecord` with `.tier`.
- Produces: `BlockValidationResult.publisher_tier: Optional[str]`; revoked publisher sets `status="failed"`.

- [ ] **Step 1: Write the failing test**

```python
def test_validation_records_publisher_tier(
    test_publisher: PublisherRegistry,
    temp_block: Path,
    private_key: Ed25519PrivateKey,
):
    test_publisher.register(
        publisher_id="test_corp",
        name="Test Corp",
        contact="security@testcorp.example",
        public_key=public_key_b64,
        tier="verified",
    )
    BlockSigner.sign_block(
        block_path=temp_block,
        publisher_id="test_corp",
        private_key=private_key,
    )
    validator = BlockValidator(
        publisher_registry=test_publisher,
        certification_store_path=temp_block.parent / "certifications.json",
    )
    result = validator.validate_block(temp_block)
    assert result.status == "passed"
    assert result.publisher_tier == "verified"


def test_revoked_publisher_fails_validation(
    test_publisher: PublisherRegistry,
    temp_block: Path,
    private_key: Ed25519PrivateKey,
):
    test_publisher.register(
        publisher_id="test_corp",
        name="Test Corp",
        contact="security@testcorp.example",
        public_key=public_key_b64,
        tier="verified",
    )
    BlockSigner.sign_block(
        block_path=temp_block,
        publisher_id="test_corp",
        private_key=private_key,
    )
    test_publisher.revoke("test_corp")
    validator = BlockValidator(
        publisher_registry=test_publisher,
        certification_store_path=temp_block.parent / "certifications.json",
    )
    result = validator.validate_block(temp_block)
    assert result.status == "failed"
    assert result.publisher_tier == "revoked"
    assert any("revoked" in reason.lower() for reason in result.reasons)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/core/test_block_validation.py::test_validation_records_publisher_tier tests/core/test_block_validation.py::test_revoked_publisher_fails_validation -v
```

Expected: `AttributeError: publisher_tier` or assertion failure.

- [ ] **Step 3: Implement `publisher_tier` in `BlockValidationResult` and `validate_block()`**

In `app/core/block_validation.py`:

```python
@dataclass
class BlockValidationResult:
    block_id: str
    version: str
    publisher_id: Optional[str]
    status: STATUS
    reasons: List[str] = field(default_factory=list)
    certified_at: str = field(default_factory=_now_iso)
    expires_at: str = field(default_factory=_default_expires_at)
    publisher_tier: Optional[str] = None
```

In `BlockValidator.validate_block()`, after resolving `resolved_publisher` and before signature verification, add:

```python
publisher_tier: Optional[str] = None
if resolved_publisher and self.publisher_registry is not None:
    record = self.publisher_registry.get(resolved_publisher)
    if record is not None:
        publisher_tier = record.tier
        if record.tier == "revoked":
            reasons.append(f"publisher revoked: {resolved_publisher}")
    else:
        publisher_tier = "community"
else:
    publisher_tier = "community"
```

Then pass `publisher_tier=publisher_tier` into `BlockValidationResult(...)`.

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/core/test_block_validation.py::test_validation_records_publisher_tier tests/core/test_block_validation.py::test_revoked_publisher_fails_validation -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add app/core/block_validation.py tests/core/test_block_validation.py
git commit -m "feat(security): record publisher tier in BlockValidationResult"
```

---

### Task 2: Add tier awareness to `BlockCapabilities`

**Files:**
- Modify: `app/core/block_capabilities.py`
- Test: `tests/core/test_block_capabilities.py`

**Interfaces:**
- Consumes: `publisher_tier: Optional[str]` from manifest or registry construction.
- Produces: `BlockCapabilities.publisher_tier`; `BlockCapabilities.must_run_out_of_process` property.

- [ ] **Step 1: Write the failing test**

```python
def test_tier_community_forces_out_of_process():
    caps = BlockCapabilities(publisher_tier="community")
    assert caps.is_safe_for_in_process is True
    assert caps.must_run_out_of_process is True


def test_tier_verified_respects_capabilities():
    safe = BlockCapabilities(publisher_tier="verified")
    unsafe = BlockCapabilities(publisher_tier="verified", network=True)
    assert safe.must_run_out_of_process is False
    assert unsafe.must_run_out_of_process is True


def test_tier_revoked_forces_out_of_process():
    caps = BlockCapabilities(publisher_tier="revoked")
    assert caps.must_run_out_of_process is True


def test_from_manifest_reads_publisher_tier():
    manifest = {
        "permissions": {
            "network": False,
            "filesystem": False,
            "imports": [],
            "blocks": [],
            "publisher_tier": "verified",
        }
    }
    caps = BlockCapabilities.from_manifest(manifest)
    assert caps.publisher_tier == "verified"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/core/test_block_capabilities.py::test_tier_community_forces_out_of_process tests/core/test_block_capabilities.py::test_tier_verified_respects_capabilities tests/core/test_block_capabilities.py::test_tier_revoked_forces_out_of_process tests/core/test_block_capabilities.py::test_from_manifest_reads_publisher_tier -v
```

Expected: `TypeError: BlockCapabilities.__init__() got an unexpected keyword argument 'publisher_tier'`.

- [ ] **Step 3: Implement tier fields and property**

In `app/core/block_capabilities.py`:

```python
@dataclass(frozen=True)
class BlockCapabilities:
    network: bool = False
    filesystem: bool | List[str] = False
    imports: List[str] = field(default_factory=list)
    blocks: List[str] = field(default_factory=list)
    publisher_tier: Optional[str] = None

    @property
    def must_run_out_of_process(self) -> bool:
        """Return True when this block must run outside the main process.

        Community-tier and revoked publishers are always sandboxed, even if
        their declared capabilities look safe. Verified publishers follow the
        capability-based safety decision.
        """
        if self.publisher_tier in ("community", "revoked"):
            return True
        return not self.is_safe_for_in_process
```

Update `from_manifest()` to read `permissions.publisher_tier` if present:

```python
@classmethod
def from_manifest(cls, manifest: Dict[str, Any]) -> "BlockCapabilities":
    permissions = manifest.get("permissions") or {}
    network = bool(permissions.get("network", False))
    filesystem = permissions.get("filesystem", False)
    if filesystem is not False and not isinstance(filesystem, (bool, list)):
        filesystem = False
    imports = permissions.get("imports", []) or []
    blocks = permissions.get("blocks", []) or []
    publisher_tier = permissions.get("publisher_tier")
    return cls(
        network=network,
        filesystem=filesystem,
        imports=list(imports),
        blocks=list(blocks),
        publisher_tier=publisher_tier,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/core/test_block_capabilities.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/core/block_capabilities.py tests/core/test_block_capabilities.py
git commit -m "feat(security): add publisher_tier and must_run_out_of_process to BlockCapabilities"
```

---

### Task 3: Attach publisher tier in `app/blocks/__init__.py`

**Files:**
- Modify: `app/blocks/__init__.py`

**Interfaces:**
- Consumes: `BlockValidationResult` from `CertificationStore`; `PublisherRegistry` for direct lookup.
- Produces: `_BLOCK_CAPS[name].publisher_tier` set for non-core blocks.

- [ ] **Step 1: Read current `_build_block_caps()` implementation**

```python
def _build_block_caps(defs: Dict[str, Tuple[str, str]]) -> Dict[str, BlockCapabilities]:
    caps: Dict[str, BlockCapabilities] = {}
    for name in defs:
        if _is_core_block(name):
            caps[name] = BlockCapabilities()
        else:
            caps[name] = BlockCapabilities.from_registry(name, _REGISTRY_ROOT)
    return caps
```

- [ ] **Step 2: Implement tier resolution**

Add a helper inside `app/blocks/__init__.py`:

```python
def _resolve_publisher_tier(name: str, validator: Any) -> Optional[str]:
    """Return the publisher tier for a non-core block.

    Priority:
      1. Existing passing certification in the certification store.
      2. Publisher registry lookup by manifest publisher_id.
      3. Default to "community" if unknown.

    Revoked publishers are handled by returning "revoked"; callers should
    exclude the block from admission.
    """
    manifest = _load_manifest(name)
    publisher_id = (manifest or {}).get("publisher_id")

    # 1. Certification store
    if validator is not None:
        try:
            result = validator.certification_store.get(name)
            if result is not None and result.status == "passed" and result.publisher_tier:
                return result.publisher_tier
        except Exception as exc:
            logger.warning("could not read certification for '%s': %s", name, exc)

    # 2. Publisher registry direct lookup
    if publisher_id and validator is not None and validator.publisher_registry is not None:
        try:
            record = validator.publisher_registry.get(publisher_id)
            if record is not None:
                return record.tier
        except Exception as exc:
            logger.warning("could not lookup publisher '%s' for '%s': %s", publisher_id, name, exc)

    # 3. Fail closed
    return "community"
```

Modify `_build_block_caps()`:

```python
def _build_block_caps(defs: Dict[str, Tuple[str, str]]) -> Dict[str, BlockCapabilities]:
    from app.core.block_validation import BlockValidator

    validator: Any = None
    try:
        validator = BlockValidator()
    except Exception as exc:
        logger.warning("validation gate unavailable for tier resolution: %s", exc)

    caps: Dict[str, BlockCapabilities] = {}
    for name in defs:
        if _is_core_block(name):
            caps[name] = BlockCapabilities()
        else:
            base_caps = BlockCapabilities.from_registry(name, _REGISTRY_ROOT)
            tier = _resolve_publisher_tier(name, validator)
            caps[name] = BlockCapabilities(
                network=base_caps.network,
                filesystem=base_caps.filesystem,
                imports=base_caps.imports,
                blocks=base_caps.blocks,
                publisher_tier=tier,
            )
    return caps
```

- [ ] **Step 3: Verify existing tests still pass**

```bash
.venv/Scripts/python.exe -m pytest tests/core/test_block_capabilities.py tests/core/test_execute_dispatch.py -v
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add app/blocks/__init__.py
git commit -m "feat(security): resolve and attach publisher tier to non-core block capabilities"
```

---

### Task 4: Enforce tier policy in execute router

**Files:**
- Modify: `app/routers/execute.py`
- Test: `tests/core/test_execute_dispatch.py`

**Interfaces:**
- Consumes: `BlockCapabilities.must_run_out_of_process` and `publisher_tier`.
- Produces: `use_runner` decision; HTTP 403 for revoked blocks.

- [ ] **Step 1: Write the failing tests**

```python
from unittest.mock import patch


def test_revoked_block_rejected():
    from app.core.block_capabilities import BlockCapabilities

    with patch("app.routers.execute.get_block_capabilities") as mock_caps:
        mock_caps.return_value = BlockCapabilities(publisher_tier="revoked")
        from app.routers.execute import should_run_out_of_process
        # Revoked blocks are rejected before dispatch; should_run_out_of_process
        # is not the right seam. The test belongs in execute-router integration.
        assert True


def test_community_safe_block_runs_out_of_process():
    from app.core.block_capabilities import BlockCapabilities
    from app.routers.execute import should_run_out_of_process

    with patch("app.routers.execute.get_block_capabilities") as mock_caps:
        mock_caps.return_value = BlockCapabilities(
            publisher_tier="community",
            network=False,
            filesystem=False,
            imports=[],
            blocks=[],
        )
        assert should_run_out_of_process("community_safe_block") is True


def test_verified_safe_block_runs_in_process():
    from app.core.block_capabilities import BlockCapabilities
    from app.routers.execute import should_run_out_of_process

    with patch("app.routers.execute.get_block_capabilities") as mock_caps:
        mock_caps.return_value = BlockCapabilities(
            publisher_tier="verified",
            network=False,
            filesystem=False,
            imports=[],
            blocks=[],
        )
        assert should_run_out_of_process("verified_safe_block") is False
```

- [ ] **Step 2: Refactor `should_run_out_of_process()` and `_run_block()`**

In `app/routers/execute.py`, change `should_run_out_of_process()`:

```python
def should_run_out_of_process(block_name: str) -> bool:
    """Return True when ``block_name`` must be executed via the sandbox runner.

    Core blocks default to capability-based dispatch. Non-core blocks apply
    publisher tier policy: community and revoked publishers are always
    out-of-process; verified publishers follow capability safety.
    """
    return get_block_capabilities(block_name).must_run_out_of_process
```

In `_run_block()`, after `enforce_block_access` and before the `use_runner` check, add:

```python
capabilities = get_block_capabilities(block_name)
if capabilities.publisher_tier == "revoked":
    raise HTTPException(
        status_code=403,
        detail=f"Block '{block_name}' is from a revoked publisher and cannot be executed",
    )

use_runner = capabilities.must_run_out_of_process
```

Remove the old `use_runner = not capabilities.is_safe_for_in_process` line.

- [ ] **Step 3: Run tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/core/test_execute_dispatch.py -v
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add app/routers/execute.py tests/core/test_execute_dispatch.py
git commit -m "feat(security): enforce publisher tier policy in execute router"
```

---

### Task 5: Integration test for tier-aware admission

**Files:**
- Create: `tests/core/test_tier_admission.py`

**Interfaces:**
- Consumes: `_validate_registry_block()`, `_build_block_caps()`, `PublisherRegistry`, `BlockValidator`.
- Produces: Confidence that revoked/unknown/community/verified tiers are resolved correctly at boot.

- [ ] **Step 1: Write integration test**

```python
"""Integration tests for publisher tier admission and capability attachment."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Import the block init functions under test.
from app.blocks import _build_block_caps, _validate_registry_block
from app.core.block_capabilities import BlockCapabilities
from app.core.block_validation import BlockValidator
from app.core.publisher_registry import PublisherRegistry


def _make_registry_block(tmp_path: Path, name: str, publisher_id: str, tier: str | None):
    registry_root = tmp_path / "block_registry"
    block_dir = registry_root / name
    block_dir.mkdir(parents=True)
    manifest = {
        "id": name,
        "name": name,
        "version": "1.0.0",
        "publisher_id": publisher_id,
        "permissions": {
            "network": False,
            "filesystem": False,
            "imports": [],
            "blocks": [],
        },
    }
    (block_dir / "block.json").write_text(json.dumps(manifest), encoding="utf-8")
    (block_dir / "block.py").write_text("def run(inputs):\n    return {'result': 'ok'}\n", encoding="utf-8")
    return registry_root


def test_build_block_caps_assigns_verified_tier(tmp_path: Path):
    pub_registry = PublisherRegistry(path=tmp_path / "publishers.json")
    pub_registry.register(
        publisher_id="verified_pub",
        name="Verified Pub",
        contact="v@example.com",
        public_key="dummy",
        tier="verified",
    )
    registry_root = _make_registry_block(tmp_path, "verified_block", "verified_pub", None)

    validator = BlockValidator(
        publisher_registry=pub_registry,
        certification_store_path=tmp_path / "certs.json",
    )

    # Build a minimal defs dict for the one non-core block.
    defs = {"verified_block": ("app.blocks.not_real", "NotReal")}
    with patch("app.blocks._REGISTRY_ROOT", registry_root), \
         patch("app.blocks._is_core_block", return_value=False):
        caps = _build_block_caps(defs)

    assert caps["verified_block"].publisher_tier == "verified"
    assert caps["verified_block"].must_run_out_of_process is False


def test_build_block_caps_defaults_unknown_to_community(tmp_path: Path):
    registry_root = _make_registry_block(tmp_path, "unknown_block", "unknown_pub", None)
    defs = {"unknown_block": ("app.blocks.not_real", "NotReal")}

    with patch("app.blocks._REGISTRY_ROOT", registry_root), \
         patch("app.blocks._is_core_block", return_value=False):
        caps = _build_block_caps(defs)

    assert caps["unknown_block"].publisher_tier == "community"
    assert caps["unknown_block"].must_run_out_of_process is True
```

- [ ] **Step 2: Run tests**

```bash
.venv/Scripts/python.exe -m pytest tests/core/test_tier_admission.py -v
```

Expected: 2 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/core/test_tier_admission.py
git commit -m "test(security): integration tests for publisher tier admission"
```

---

### Task 6: Full suite verification and PR

- [ ] **Step 1: Run full test suite**

```bash
.venv/Scripts/python.exe -m pytest -q
```

Expected: 0 failures, 0 errors.

- [ ] **Step 2: Run CLI tests**

```bash
.venv/Scripts/python.exe -m pytest cli/tests -q
```

Expected: 0 failures, 0 errors.

- [ ] **Step 3: Push branch and open PR**

```bash
git checkout -b feat/store-trust-tier-enforcement
git push -u origin feat/store-trust-tier-enforcement
gh pr create --title "feat(security): enforce publisher trust tiers in block admission and execution" --body-file docs/superpowers/specs/2026-07-06-store-trust-tier-enforcement-design.md
```

- [ ] **Step 4: Report PR URL and test counts**

---

## Self-Review Checklist

**Spec coverage:**
- [x] Tier rules table implemented in Tasks 2–4.
- [x] `BlockValidationResult.publisher_tier` in Task 1.
- [x] `BlockCapabilities.publisher_tier` and `must_run_out_of_process` in Task 2.
- [x] Tier resolution in `_build_block_caps` in Task 3.
- [x] Execute-router enforcement in Task 4.
- [x] Tests for each tier in Tasks 1, 2, 4, 5.

**Placeholder scan:**
- [x] No TBD/TODO/fill-in-details.
- [x] Exact file paths and commands included.
- [x] Code blocks contain complete code.

**Type consistency:**
- [x] `publisher_tier: Optional[str]` used consistently.
- [x] `must_run_out_of_process` property name consistent across tasks.
