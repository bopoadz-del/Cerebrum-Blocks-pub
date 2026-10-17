# Corrected Action Plan: Cerebrum-Blocks ↔ The_Fork ↔ <private-repo>

## Architecture Relationship

| Repository | Role |
|------------|------|
| **Cerebrum-Blocks** | The App Store / block marketplace. Single source of truth for blocks, kits, and containers. |
| **<private-repo>** | The storefront configurator. Users pick blocks + choose a domain kit; it assembles a deployable platform skeleton. |
| **The_Fork** | The first real, deployed platform — construction-specialized, battle-tested, and proven working. It is the reference deployment, not a competing codebase. |

## Guiding Principle

The_Fork contains practical, hardened improvements that should flow **back upstream** into Cerebrum-Blocks so the next Finance / Legal / Medical platform starts from proven code, not theory.

## Priority Roadmap

| Priority | Action | Why |
|----------|--------|-----|
| **P0** | Port the modular `construction/` container from The_Fork → `Cerebrum-Blocks/app/containers/construction/` | The 7,478-line monolith is the biggest store liability. |
| **P1** | Port The_Fork-only blocks into Cerebrum-Blocks (`safety_world_detector`, `construction_advisor`, `historical_benchmark`, `mcp_adapter`, `mcp_consumer`) | These are proven, deployable blocks missing from the store. |
| **P2** | Back-port RAG / chat / agent improvements from The_Fork into Cerebrum-Blocks core | The_Fork’s RAG pipeline is deployed and tested. |
| **P3** | Clean Cerebrum-Blocks legacy layers (`blocks/` root, `app/blocks_legacy/`, `app/containers_legacy/`) | Remove confusion so the store has one clear block pattern. |
| **P4** | Update <private-repo> configurator to assemble platforms closer to The_Fork’s architecture | Users get a deployable platform, not just a demo. |

## Reference Deployment Policy

- **The_Fork** stays the construction reference platform.
- **Cerebrum-Blocks** becomes the single source of truth for blocks + kits.
- **<private-repo>** generates new forks (Finance, Legal, Medical, etc.) by copying The_Fork’s skeleton and swapping the domain kit.

## Current Status

- Marker PDF integration: complete, local-only.
- P3 cleanup: `app/blocks_legacy/`, `app/containers_legacy/`, and the legacy `blocks/` root removed.
- P0 + P1 complete: modular construction container and missing Fork blocks ported.
- Next: P2 (RAG/chat/agent back-port) and P4 (<private-repo> configurator alignment).
- Security layer (auth/memory/monitoring) is now a generic, always-loaded trust layer to support third-party blocks in the store.
