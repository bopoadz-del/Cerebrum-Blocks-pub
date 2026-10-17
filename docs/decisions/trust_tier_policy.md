# Publisher Trust Tier Policy

## Tiers

| Tier | Meaning | Runtime treatment |
|------|---------|-------------------|
| `community` | Unknown or uncertified publisher | Always sandboxed, regardless of declared capabilities |
| `reviewed` | Publisher vetted by the platform | May run in-process when capabilities are safe; sandboxed when unsafe |
| `certified` | Pilot-proven / platform-trusted | May run in-process, including with elevated capabilities |
| `revoked` | Explicitly revoked | Rejected at admission and runtime |

## Source of truth

Tier is a **platform assertion**, not a block self-declaration. It is resolved from:

1. The live publisher registry (`data/publishers.json`).
2. A cached, non-expired certification record.
3. Defaulting to `community` if unknown.

## Why name-based auto-promotion was removed

Previously, blocks bundled with the platform in `_EXTENDED_BLOCK_DEFS` were automatically promoted from `community` to `verified` based only on their block name. This created a spoofing bypass: a third-party block that reused the name of a platform extended block (e.g., `local_drive`) could inherit platform trust and run in-process.

Platform extended blocks now receive the platform tier only when their manifest declares the platform `publisher_id` and the registry records that publisher as `reviewed` or `certified`. The publisher registry is the sole source of tier truth.
