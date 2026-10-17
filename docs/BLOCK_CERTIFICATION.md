# Block certification — the three bars

Port of the Construction Capability Audit discipline (The_Fork) to the
Store. A block is **certified** only when it passes all three bars, run
by `scripts/certify_block.py`:

| Bar | Question | Instrument |
| --- | --- | --- |
| 1 | **Not a stub.** Does the entry method have a real body? | AST hollow-body check on the defining source |
| 2 | **Current.** Does the advertised id resolve to one importable implementation with identity metadata? | import check + `block_registry/<id>/block.json` identity keys (`id`, `name`, `version`) |
| 3 | **Really tested.** Would the suite notice if it broke? | **Control-delete**: the entry method is gutted to a plausible success (`{"block": <name>, "status": "success"}`) and the block's tests MUST go RED |

Bar 3 is the one that finds things. A capability can be real, current and
completely unprotected — the suite that stays green on a plausible-success
gut proves nothing about the block's payloads.

## Rules

- **Baseline GREEN first.** The mutation run only counts when the
  un-mutated suite passes.
- **The mutation lands where the method is defined.** An entry inherited
  from a shared base (`TypedBlock.execute`) mutates that base — the
  harness records it as a NOTE, not a failure.
- **The file must be clean** (`git status` empty for it) before mutating;
  the harness restores it via `git checkout` in a `finally`.
- **Real fixtures.** New certifications must name a real input artifact
  exercised by the tests (file, image, schedule). In-test generated
  artifacts are named as such. The audit's strongest predictor: the one
  capability that survived every bar had a real file behind its tests.

## Registry

`block_certifications.json` is the source of truth: `module`, `class`,
`method`, `tests`, `fixture`, `certified`, `include_in_ci`.

- `include_in_ci: true` entries run on every CI push via
  `python scripts/certify_block.py --all`.
- A block that fails bar 3 is **not removed from CI** — it is marked
  `certified: false` with the failing bar recorded, so the fix is tracked
  instead of silently dropped.

## Certifying a new block

1. Ensure the block has payload-asserting tests (not shape-only).
2. Add an entry to `block_certifications.json` with its real fixture.
3. `python scripts/certify_block.py --block <id>` — fix until PASS.
4. Set `include_in_ci: true` once green.

## Current roster

| block | entry | fixture |
| --- | --- | --- |
| chat | ChatBlock.execute (inherited TypedBlock) | mock provider envelope (in-test) |
| capture | CaptureBlock.execute (inherited TypedBlock) | PIL image rendered in-test |
| knowledge | KnowledgeBlock.execute | — |
| pdf | PDFBlock.execute (inherited TypedBlock) | PDF written in-test |
| image | ImageBlock.execute (inherited UniversalBlock) | PIL image in-test |
| agent_swarm | AgentSwarmBlock.execute | — |
| sandbox | SandboxBlock.process | real Python source executed through the restricted in-process exec + fake runner transport |
| cache_manager | CacheManagerBlock.process | injected cache client, round-tripped under real `scope_key()` tenant/project/class keys |
| local_drive | LocalDriveBlock.process | real files written to and read back from a tmp_path drive root |
| google_drive | GoogleDriveBlock.process | RSA-2048 key generated in-test; a real RS256 service-account JWT minted and decoded |

### Entered, not yet certified

Recorded per the rule above — failing bar 3 is tracked here, not dropped.
Every one of these fails for the *same* reason: the block's only tests
assert the `UniversalBlock` envelope (`block`, `request_id`, `status`,
`result`, …), and `execute()` supplies those keys whatever `process()`
returns. Shape-only tests cannot notice a gutted entry method.

| block | entry | failing bar |
| --- | --- | --- |
| onedrive | OneDriveBlock.process | 3 — envelope-only tests stay green on the gut |
| search | SearchBlock.process | 3 — envelope-only tests stay green on the gut |
| translate | TranslateBlock.process | 3 — no test reads `result["result"]["translated"]` |
| web | WebBlock.process | 3 — envelope-only tests stay green on the gut |
| learning_engine | LearningEngineBlock.process | 3 — no test calls `process()`/`execute()` at all; every test reaches into `_save_state`/`_store` directly, so the dispatcher is uncovered |
| webhook | WebhookBlock.process | 3 not runnable — the Store has no test for this block (`tests/blocks/test_inbound_webhook.py` covers the *different* `inbound_webhook` block) |
