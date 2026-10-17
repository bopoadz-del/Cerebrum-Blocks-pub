# Cerebrum Sandbox Runner

Isolated FastAPI service that executes user-supplied Python or argv-split
shell commands for the `code`, `sandbox`, and `formula_executor.custom_code`
blocks. Exists so the API worker never spawns untrusted code in its own
process namespace.

## Build

    docker build -t cerebrum-sandbox-runner ./sandbox-runner

## Run (hardened — operator command)

    docker run --rm -p 8001:8001 \
      --read-only \
      --tmpfs /scratch:size=64m,mode=1777 \
      --network=none \
      --cap-drop=ALL \
      --pids-limit=128 \
      --memory=256m --cpus=0.5 \
      --user=999:999 \
      cerebrum-sandbox-runner

For Render private services, the network restriction comes from the
private-network boundary; `--network=none` is for self-hosted operators.

## Endpoints

- `GET /health` — liveness probe (`{"status":"ok"}`).
- `POST /exec` — body `{language: "python"|"bash", code, input_values, timeout_s}`,
  returns `{status, result, stdout, stderr, elapsed_ms, exit_code, timed_out}`.

## Env

None. The container deliberately runs with no inherited env — the parent
worker should not pass any secrets through.

## Threat model

Trusted: container-level isolation (`--read-only`, dropped caps, no net,
unprivileged uid). Not trusted: kernel-level escapes — that's a future
gVisor/Kata upgrade. Per-request scratch dirs are wiped after exec.
