# Parked Blockers

- Registry block signing: **resolved** (Phase 5). A platform keypair was
  generated; all 105 `block_registry` blocks are signed and verify, and the
  private key is held in the owner's secrets manager — never committed.
  Rotate with `scripts/rotate_publisher_key.py`. Remaining: domain-kit
  *bundle* signing (kit installs are provenance-verified via sha256 today,
  not Ed25519-signed).
- `CEREBRUM_DOMAIN_KITS=insurance` capability declaration warnings for
  `insurance` / `insurance_v2`: **resolved** by adding
  `block_registry/insurance/block.json` and
  `block_registry/insurance_v2/block.json`.
- Starlette pytest filter: **resolved** in `pytest.ini` (use
  `ignore::DeprecationWarning:starlette`).
