# cerebrum-cli

Thin terminal client for <private-repo> instances. Only runtime dependency: `httpx`.

## Install

```bash
cd cli
pip install -e .
```

## Auth

Resolution order: CLI flag > environment variable > `~/.cerebrum/config.toml`.

| Mode | Flag | Env |
|------|------|-----|
| JWT token | `--token` | `CEREBRUM_TOKEN` |
| API key | `--api-key` | `CEREBRUM_API_KEY` |
| Email/password | `--email` / `--password` | `CEREBRUM_EMAIL` / `CEREBRUM_PASSWORD` |

Email/password mode POSTs to `/v1/users/login` and caches the returned token in-process.

## Config

```bash
cerebrum init              # interactive config writer
cerebrum init --mode deployed  # non-interactive mode selection
cerebrum config            # show resolved config (api_key masked)
```

`~/.cerebrum/config.toml`:

```toml
base_url = "https://cerebrumdev-backend.onrender.com"
api_key = "cb_prod_..."
domain = "construction"
instance_name = "prod"
session_id = "sess_..."
mode = "configurator"   # or "deployed"
```

## Modes

The CLI operates in one of two modes:

- **`configurator`** (default): targets a live configurator session. `cerebrum chat`
  POSTs to `/v1/sessions/{session_id}/chat` and requires `--session` or a
  configured `session_id`.
- **`deployed`**: targets a packaged/deployed instance. `cerebrum chat` POSTs to
  `/v1/deployed/chat` with body `{"message": ..., "history": []}`. No session
  ID is required; any provided session ID is ignored.

Set the mode interactively with `cerebrum init` or override with `--mode`.

## Usage

```bash
cerebrum health
cerebrum chat "list blocks" --session sess_abc123
cerebrum chat --repl --session sess_abc123
cerebrum chat "list blocks" --events   # show heartbeats/first-token marks, suppress tokens
cerebrum chat "list blocks" --raw      # dump raw SSE data lines

# deployed mode: no session id required
cerebrum --mode deployed chat "list blocks"

cerebrum upload file1.pdf file2.txt --session sess_abc123
cerebrum chain show --session sess_abc123
cerebrum deploy status --session sess_abc123
```

## Notes

- `cerebrum init` can run from a pipe: when stdin is not a TTY and `--mode`
  is omitted, it defaults to `configurator` and prints an informational message
  to stderr. Use `--mode deployed` to choose deployed mode non-interactively.
- The CLI targets the canonical SSE envelope (`data:` lines with JSON `type`).
- CerebrumDev's configurator router currently uses a different named-event format; a future Spec 2 PR standardizes the servers.
- `reindex` and `rules list` are reserved for deployed-instance endpoints and print a clear "not available" message until those endpoints exist.
