# Design: Docker sandbox for `formula_executor` / `code` / `sandbox` blocks

**Status:** Not implemented. This doc scopes the work; nothing in code is
gated on it yet.

## Why

The audit (commit `2ca14353`) flagged three blocks that ship with broken
Python sandboxes:

- `code`: runs `subprocess.run([sys.executable, tmp])` with the worker's
  full `os.environ`. Master-key holders effectively have RCE + env-var
  exfil.
- `sandbox`: bash mode allowlists only the first token, then passes the
  full string to `create_subprocess_shell`. Shell metacharacters bypass.
- `formula_executor`: `exec()` with `__builtins__={}`. Escapable via
  `().__class__.__bases__[0].__subclasses__()`.

Today, all three are restricted to `tier=unlimited` keys (admin role
only). That neutralises the public threat. The remaining risk: an admin
key on a public-internet SaaS gets phished/leaks at some point. When
that happens, the same-RCE pattern lights up.

The fix is real isolation, not better in-process tricks.

## Goals

- Run user-supplied code (Python or shell) in a process namespace that
  cannot:
  - Read environment variables of the worker
  - Reach the network (no DNS, no outbound TCP/UDP)
  - Read or write files outside a per-execution scratch dir
  - Persist anything beyond its lifetime
  - Consume more than configurable CPU / memory / wall time
- Round-trip for a simple formula evaluation in <250ms p99 once the
  sandbox is warm; <1.5s including cold spawn.

## Non-goals (this iteration)

- gVisor / Kata-grade kernel-attack resistance. We assume the attacker
  is admin-key-equivalent (i.e. trusted to not run zero-days against
  the kernel — they're paying us). Defence-in-depth comes later.
- Multi-tenant isolation between simultaneous calls. Single executor
  per worker, queued.
- GPU access from inside the sandbox.

## Three viable approaches, ordered by effort

### 1. `firejail` profile (low effort, partial)

Run subprocesses with `firejail --quiet --noprofile --net=none
--private --rlimit-as=512000000 --rlimit-cpu=10 -- <cmd>`. Drops env
(`--private` makes `/root` and `/home/<user>` empty), no network,
filesystem fresh tmpfs.

**Pros:** Already on most Debian/Ubuntu base images; one-line wrap; no
infra changes.

**Cons:** Has had its share of CVEs (suid binary, profile escapes).
Still in-process from the worker's view — env still readable to it,
just not to the child.

**Time estimate:** 1 day to wrap the three blocks; 1-2 days to write
proper integration tests + a deny-list of known firejail-escape
patterns.

### 2. Separate Docker container for code execution (medium effort, recommended)

Architecture:

```
api worker  ──REST──▶  sandbox-runner  ──exec──▶  python -E -S /code/main.py
                       (separate                    (no env, no net,
                       container, no                read-only rootfs +
                       net access)                  scratch tmpfs)
```

- Add `cerebrum-sandbox-runner` as a sibling Render service (or
  docker-compose service in dev).
- Build it from a minimal base (`python:3.11-slim` or `gvisor`'s `runsc`
  with a Python rootfs).
- Run with `--read-only`, `--network=none`, `--cap-drop=ALL`,
  `--user=nobody`, `--tmpfs /scratch:size=100m`, `--memory=256m`,
  `--cpus=0.5`, `--pids-limit=64`, `--ulimit nofile=64:64`.
- Worker calls it via `httpx.AsyncClient` over a private network
  (Render private network, or docker-compose internal network).
- Wire the existing `code` / `sandbox` / `formula_executor.custom_code`
  paths to call the runner instead of running locally.

**Pros:** Real isolation. Easy to monitor (separate logs, separate
metrics). Scales horizontally. Can run on gVisor if Render supports it
later.

**Cons:** Network hop; extra deploy; cold-start when the runner sleeps.

**Time estimate:** 3 days for the runner service (build, deploy, wire
into existing blocks); 2 days for hardening + integration tests.

### 3. WASI / WebAssembly (high effort, future-proof)

Use `wasmtime`-py to run user code as a WASM module. Python source
compiled to WASM via `pyodide` or similar.

**Pros:** Strong sandbox, no syscalls except via explicit WASI imports,
deterministic resource limits. Cross-language: same harness can run JS,
Rust, etc.

**Cons:** Pyodide is heavy (~12MB), startup non-trivial. Not all Python
libraries work in WASI. CoolProp / QuantLib won't.

**Time estimate:** 1-2 weeks. Probably overkill for the current threat
model.

## Recommendation

**Approach 2 (Docker runner).** firejail is too brittle long-term;
WASI is too much work for what we need. The Docker runner gives us
real isolation, fits the existing Render multi-service deploy model,
and lets us swap to gVisor / Kata later without touching the worker
code (only the runner image changes).

## Concrete next steps

1. Write `sandbox-runner/Dockerfile` (Python 3.11, nobody user,
   read-only rootfs).
2. Write `sandbox-runner/server.py` — minimal FastAPI with one POST
   `/exec` accepting `{code, language, input_values, timeout_seconds}`.
3. Add `sandbox-runner` to `render.yaml` as `type: pserv` (private
   service). Set `numInstances: 1` to start. Wire `SANDBOX_RUNNER_URL`
   env on the API service.
4. Refactor `app/blocks/code.py:_run_python` and
   `app/blocks/sandbox.py:_execute_python` / `_execute_bash` to call
   the runner via HTTPX with the existing per-block timeout / params.
   Keep the in-process implementation as a fallback for dev when
   `SANDBOX_RUNNER_URL` is unset.
5. Refactor `app/blocks/formula_executor.py:_execute_sandbox` similarly.
6. Add integration tests that:
   - Drop env entirely (verify `os.environ` is empty inside).
   - Try to import `socket` and connect — verify failure.
   - Try to read `/etc/passwd` — verify failure.
   - Verify timeout enforcement.
   - Verify memory cap (allocate 1GB → killed).

## Until this lands

- All three blocks remain in `RESTRICTED_BLOCKS` (unlimited tier only).
- The `_validate_code` static checks in `sandbox.py` still apply as
  defence-in-depth even after the runner ships.
