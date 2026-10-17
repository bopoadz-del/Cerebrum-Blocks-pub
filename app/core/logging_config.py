"""Structured logging + optional Sentry initialization.

Call configure_logging() and init_sentry() once at app startup, before any
loggers emit records. Both are idempotent and safe to call when the env vars
they depend on are unset.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from typing import Any


_RESERVED_LOGRECORD_ATTRS = {
    "args", "asctime", "created", "exc_info", "exc_text", "filename",
    "funcName", "levelname", "levelno", "lineno", "message", "module",
    "msecs", "msg", "name", "pathname", "process", "processName",
    "relativeCreated", "stack_info", "thread", "threadName", "taskName",
}


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record. Includes any `extra={}` fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # Surface caller-supplied extras
        for k, v in record.__dict__.items():
            if k in _RESERVED_LOGRECORD_ATTRS or k.startswith("_"):
                continue
            payload[k] = v
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    """Configure root logger. JSON in prod, plain text in dev.

    Honors LOG_LEVEL (default INFO) and LOG_FORMAT (json|text, default json
    in prod, text in dev).
    """
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    env = os.getenv("ENV", os.getenv("ENVIRONMENT", "production")).strip().lower()
    is_dev = env in {"dev", "development", "local", "test", "testing"}
    fmt = os.getenv("LOG_FORMAT", "text" if is_dev else "json").lower()

    handler = logging.StreamHandler(sys.stdout)
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
        )

    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)

    # Tame noisy third-party loggers without losing errors
    for noisy in ("uvicorn.access", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(max(level, logging.WARNING))


# ── Sentry event scrubbing ────────────────────────────────────────────────
#
# The audit found Sentry was initialised at defaults. The SDK attaches
# request bodies, and POST /v1/execute bodies carry plaintext customer
# secret material: `block:"secrets"` reads `input.value` verbatim
# (app/blocks/secrets.py), and the same is true for `config` and `auth`.
# Any unhandled exception on those paths shipped the plaintext to a
# third-party SaaS. Worse, the plaintext also lives in captured stack-frame
# local variables, which no amount of request-body configuration removes.
#
# `scrub_event` is the `before_send` / `before_send_transaction` hook. It
# is a plain function with no sentry_sdk dependency so it can be exercised
# directly by tests (and so this module still imports when sentry-sdk is
# not installed).

_REDACTED = "[redacted]"

# Bodies for these blocks are replaced wholesale — never field by field.
# `secrets`/`config`/`auth` handle credential material by definition;
# `database` carries connection strings and raw SQL; `billing` carries
# payment-processor identifiers.
_SENSITIVE_BLOCKS = frozenset({
    "secrets", "config", "auth", "database", "billing",
})

# The whole payload of these request fields is dropped for a sensitive block.
_SENSITIVE_BODY_FIELDS = ("input", "params", "data", "body", "config")

# Matched as substrings of the normalised (lowercased, alphanumeric-only)
# key name.
_SENSITIVE_KEY_SUBSTRINGS = (
    "password", "passwd", "passphrase", "secret", "token", "apikey",
    "authorization", "credential", "privatekey", "accesskey", "cookie",
    "masterkey", "bearer", "connectionstring", "signature", "encryptionkey",
    "sessionid", "clientid", "refreshtoken", "salt",
)

# Matched only as an exact normalised key name, so that `values`,
# `total_value`, `keywords`, `author` and similar survive.
_SENSITIVE_KEY_EXACT = frozenset({
    "value", "key", "auth", "pwd", "session", "cert", "dsn", "pin", "otp",
})

# Depth guard for pathological nesting; Sentry payloads are shallow.
_MAX_SCRUB_DEPTH = 12

# Hard cap on any request body we still let through after scrubbing.
_MAX_BODY_CHARS = int(os.getenv("SENTRY_MAX_BODY_CHARS", "2048"))

# Literals shorter than this are not worth purging from free text and
# would cause absurd collateral damage (for example a secret of "1").
_MIN_PURGE_LEN = 6


def _normalise_key(name: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _is_sensitive_key(name: Any) -> bool:
    normalised = _normalise_key(name)
    if not normalised:
        return False
    if normalised in _SENSITIVE_KEY_EXACT:
        return True
    return any(token in normalised for token in _SENSITIVE_KEY_SUBSTRINGS)


def _scrub_by_key(obj: Any, harvested: set, depth: int = 0) -> Any:
    """Recursively redact values whose key name looks sensitive.

    Every concrete string that gets redacted is added to `harvested` so a
    later pass can purge the same literal from free-text fields (exception
    messages, log entries, breadcrumb text) where it has no key name to
    give it away.
    """
    if depth > _MAX_SCRUB_DEPTH:
        return _REDACTED
    if isinstance(obj, dict):
        scrubbed = {}
        for key, val in obj.items():
            if _is_sensitive_key(key):
                _harvest(val, harvested)
                scrubbed[key] = _REDACTED
            else:
                scrubbed[key] = _scrub_by_key(val, harvested, depth + 1)
        return scrubbed
    if isinstance(obj, (list, tuple)):
        return [_scrub_by_key(item, harvested, depth + 1) for item in obj]
    return obj


def _harvest(obj: Any, harvested: set, depth: int = 0) -> None:
    """Collect every string literal under a value whose key was sensitive.

    Used when the key name already told us the entire value is secret, so
    everything beneath it is fair game for the free-text purge.
    """
    if depth > _MAX_SCRUB_DEPTH:
        return
    if isinstance(obj, str):
        if len(obj) >= _MIN_PURGE_LEN:
            harvested.add(obj)
    elif isinstance(obj, dict):
        for val in obj.values():
            _harvest(val, harvested, depth + 1)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            _harvest(item, harvested, depth + 1)


def _harvest_sensitive_keys(obj: Any, harvested: set, depth: int = 0) -> None:
    """Collect only the strings sitting under a sensitive key name.

    Used for subtrees we drop wholesale (a sensitive block's request body).
    Such a subtree is a mix of secret and benign fields — a secret `value`
    next to a `name` of "stripe_live". Harvesting indiscriminately would
    make the free-text purge blank out the benign siblings everywhere else
    in the event, destroying the diagnostic value of the report. The
    subtree itself is redacted regardless of what we harvest here.
    """
    if depth > _MAX_SCRUB_DEPTH:
        return
    if isinstance(obj, dict):
        for key, val in obj.items():
            if _is_sensitive_key(key):
                _harvest(val, harvested, depth + 1)
            else:
                _harvest_sensitive_keys(val, harvested, depth + 1)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            _harvest_sensitive_keys(item, harvested, depth + 1)


def _purge_literals(obj: Any, literals: set, depth: int = 0) -> Any:
    """Second pass: remove harvested literals from every remaining string.

    Catches the case the key-name pass structurally cannot: a secret
    interpolated into an exception message, a log record, a breadcrumb, or
    a transaction name.
    """
    if depth > _MAX_SCRUB_DEPTH or not literals:
        return obj
    if isinstance(obj, str):
        out = obj
        for literal in literals:
            if literal in out:
                out = out.replace(literal, _REDACTED)
        return out
    if isinstance(obj, dict):
        return {k: _purge_literals(v, literals, depth + 1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_purge_literals(i, literals, depth + 1) for i in obj]
    return obj


def _parse_body(data: Any) -> Any:
    """Return the request body as a structure, or None if it is not JSON."""
    if isinstance(data, (dict, list)):
        return data
    if isinstance(data, (str, bytes)):
        try:
            return json.loads(data)
        except (ValueError, TypeError):
            return None
    return None


def _scrub_request(request: Any, harvested: set) -> Any:
    """Handle the /v1/execute body specially, then scrub by key name."""
    if not isinstance(request, dict):
        return request
    request = dict(request)
    url = str(request.get("url", ""))
    data = request.get("data")
    parsed = _parse_body(data)

    if isinstance(parsed, dict):
        block = str(parsed.get("block", "")).strip().lower()
        if block in _SENSITIVE_BLOCKS:
            # Wholesale replacement. Field-by-field scrubbing of a secrets
            # payload is a losing game: the caller chooses the key names.
            parsed = dict(parsed)
            for field in _SENSITIVE_BODY_FIELDS:
                if field in parsed:
                    _harvest_sensitive_keys(parsed[field], harvested)
                    parsed[field] = _REDACTED
        request["data"] = parsed
    elif data is not None and "/execute" in url:
        # An execute body we cannot parse is one we cannot reason about.
        request["data"] = _REDACTED
    elif isinstance(data, str) and len(data) > _MAX_BODY_CHARS:
        request["data"] = data[:_MAX_BODY_CHARS] + "...[truncated]"

    request = _scrub_by_key(request, harvested)

    body = request.get("data")
    if isinstance(body, str) and len(body) > _MAX_BODY_CHARS:
        request["data"] = body[:_MAX_BODY_CHARS] + "...[truncated]"
    return request


def scrub_event(event: Any, hint: Any = None) -> Any:
    """Sentry `before_send` hook. Never raises; drops the event on error.

    Scrubbing is applied to the subtrees that carry caller data — request,
    stack-frame locals, extra, contexts, user, breadcrumb data — rather
    than to the whole envelope, because Sentry stores the exception message
    itself under the key `value` and blanket key-name scrubbing would
    redact every error message. The harvested-literal pass then removes the
    same secret strings from those free-text fields.
    """
    try:
        if not isinstance(event, dict):
            return event
        event = dict(event)
        harvested: set = set()

        if "request" in event:
            event["request"] = _scrub_request(event.get("request"), harvested)

        for field in ("extra", "contexts", "user", "tags"):
            if field in event:
                event[field] = _scrub_by_key(event.get(field), harvested)

        breadcrumbs = event.get("breadcrumbs")
        crumb_list = (
            breadcrumbs.get("values")
            if isinstance(breadcrumbs, dict)
            else breadcrumbs
        )
        if isinstance(crumb_list, list):
            scrubbed_crumbs = []
            for crumb in crumb_list:
                if isinstance(crumb, dict) and "data" in crumb:
                    crumb = dict(crumb)
                    crumb["data"] = _scrub_by_key(crumb["data"], harvested)
                scrubbed_crumbs.append(crumb)
            if isinstance(breadcrumbs, dict):
                event["breadcrumbs"] = dict(breadcrumbs, values=scrubbed_crumbs)
            else:
                event["breadcrumbs"] = scrubbed_crumbs

        # Transaction events (before_send_transaction) carry spans rather
        # than an exception. Span `data` holds things like db.statement and
        # http request payloads.
        spans = event.get("spans")
        if isinstance(spans, list):
            scrubbed_spans = []
            for span in spans:
                if isinstance(span, dict) and "data" in span:
                    span = dict(span)
                    span["data"] = _scrub_by_key(span["data"], harvested)
                scrubbed_spans.append(span)
            event["spans"] = scrubbed_spans

        # Stack-frame locals are where the plaintext actually lives when a
        # block raises: `value`, `input_data`, `credentials` are all frame
        # variables at the point secrets.py fails.
        exception = event.get("exception")
        exc_values = (
            exception.get("values") if isinstance(exception, dict) else exception
        )
        if isinstance(exc_values, list):
            for exc in exc_values:
                if not isinstance(exc, dict):
                    continue
                stacktrace = exc.get("stacktrace")
                frames = (
                    stacktrace.get("frames")
                    if isinstance(stacktrace, dict)
                    else None
                )
                if not isinstance(frames, list):
                    continue
                for frame in frames:
                    if isinstance(frame, dict) and "vars" in frame:
                        frame["vars"] = _scrub_by_key(frame["vars"], harvested)

        return _purge_literals(event, harvested)
    except Exception:  # noqa: BLE001 - a failed scrub must never ship raw data
        logging.getLogger(__name__).warning(
            "sentry: event scrubbing failed; dropping event"
        )
        return None


def init_sentry() -> bool:
    """Initialize Sentry if SENTRY_DSN is set and sentry_sdk is installed.

    Returns True on success, False otherwise. Never raises.
    """
    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        return False
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
    except ImportError:
        logging.getLogger(__name__).warning(
            "SENTRY_DSN set but sentry-sdk not installed; skipping Sentry init"
        )
        return False

    env = os.getenv("ENV", os.getenv("ENVIRONMENT", "production")).strip().lower()
    # max_request_body_size is the sentry-sdk 2.x option name (requirements
    # pins sentry-sdk[fastapi]>=2.0.0). "never" means the SDK does not
    # attach request bodies at all; scrub_event is the second line of
    # defence for bodies that arrive by another route (breadcrumbs, frame
    # locals, explicit capture_message context).
    #
    # init() is guarded: it validates its own options and raises on an
    # unknown kwarg or a bad value. `init_sentry()` is called at module
    # scope in app/main.py, so an exception here would abort the import,
    # uvicorn would never bind, and the deploy would fail — in production
    # only, since that is where SENTRY_DSN is set. Losing error reporting
    # is strictly better than losing the service.
    try:
        sentry_sdk.init(
            dsn=dsn,
            environment=env,
            release=os.getenv("RELEASE_SHA") or None,
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.0")),
            send_default_pii=False,
            max_request_body_size=os.getenv("SENTRY_MAX_REQUEST_BODY_SIZE", "never"),
            before_send=scrub_event,
            before_send_transaction=scrub_event,
            integrations=[StarletteIntegration(), FastApiIntegration()],
        )
    except Exception:  # noqa: BLE001 - must never abort application startup
        logging.getLogger(__name__).exception(
            "sentry: init failed; continuing without error reporting"
        )
        return False
    return True
