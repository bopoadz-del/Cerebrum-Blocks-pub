# Canonical SSE Envelope

This document defines the Server-Sent Events (SSE) envelope used by Cerebrum
runtimes (including Cerebrum-Blocks deployed instances and The Fork) and
consumed by the `cerebrum` CLI tracer.

## Transport

- HTTP response `Content-Type: text/event-stream`.
- Each event is one line: `data: <json>\n\n`.
- Lines not beginning with `data:` are ignored by consumers.

## Event types

Every `data:` payload is a JSON object with a `type` field. Recognized types:

| type | required fields | description |
|------|-----------------|-------------|
| `route` | `type`, plus caller-defined context | Optional routing/context metadata. May be emitted before `start`. |
| `start` | `type`, optional `session_id` | First event of a turn. Signals the server accepted the request. |
| `token` | `type`, `content` | A chunk of the assistant's text response. |
| `tool_call` | `type`, `name`, optional `arguments`/`args` | A tool/block was invoked. |
| `tool_result` | `type`, `name`, optional `status` | Result of a tool invocation returned to the model. |
| `sources` | `type`, caller-defined source list | Retrieved documents/context used by RAG. |
| `heartbeat` | `type` | Keep-alive emitted during long tool waits. No semantic content. |
| `end` | `type`, optional `complete` | Exactly one terminal event on success. |
| `error` | `type`, `message` | Exactly one terminal event on failure. |

## Ordering guarantees

1. The first recognized event SHOULD be `start`.
2. Zero or more `token`, `tool_call`, `tool_result`, `sources`, and `heartbeat`
   events follow.
3. The stream MUST terminate with exactly one of `end` or `error`.
4. After `end` or `error`, the server MUST NOT emit further events.

## Heartbeat policy

- Heartbeats are emitted when the server has not produced a non-heartbeat event
  for approximately 5 seconds.
- Their purpose is to keep proxies and clients from timing out during long tool
  executions.
- Consumers MUST ignore `heartbeat` events for content rendering.

## Backward compatibility

Non-streaming endpoints that return `application/json` are not covered by this
envelope. The `cerebrum` CLI tracer falls back to printing the JSON body when a
response is not `text/event-stream`.

## Example stream

```text
data: {"type": "start", "session_id": "sess_abc123"}

data: {"type": "route", "intent": "qa"}

data: {"type": "token", "content": "The"}

data: {"type": "token", "content": " answer"}

data: {"type": "tool_call", "name": "search", "arguments": {"q": "spec clause"}}

data: {"type": "heartbeat"}

data: {"type": "tool_result", "name": "search", "status": "ok"}

data: {"type": "token", "content": " is 42."}

data: {"type": "end", "complete": true}
```
