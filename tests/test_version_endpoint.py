"""Which commit is actually serving.

Every fleet report about this service has had to write COULD NOT VERIFY
against the deployed SHA, because no HTTP route exposed it and only the
Render dashboard could settle it — while the Factory next door publishes
exactly this route. That gap is the difference between "the fix is merged"
and "the fix is live", and it is one route wide.

Unauthenticated on purpose: a deploy fact is not a secret, and a probe that
needs a credential is a probe an uptime monitor cannot make.

These tests call the handler as a function. They must not construct a
TestClient: PR #112's Full suite reached ~96% (same tail as main, ~2s
there) then hung until the 25m job timeout, on every revision that
opened a client from this file — including a bare FastAPI mount. HTTP
coverage lives on the health-router harness in
``tests/routers/test_health_capability.py``, which runs earlier and
already uses that pattern safely.
"""
from __future__ import annotations

from app.routers import health


def test_version_is_public():
    """No auth dependency on the route — a monitor cannot present a key."""
    route = next(r for r in health.router.routes if getattr(r, "path", None) == "/version")
    assert "GET" in getattr(route, "methods", set())
    names = []
    dependant = getattr(route, "dependant", None)
    if dependant is not None:
        for dep in dependant.dependencies:
            call = getattr(dep, "call", None)
            if call is not None:
                names.append(getattr(call, "__name__", ""))
    assert "require_api_key" not in names


def test_version_names_the_service_and_a_sha(monkeypatch):
    monkeypatch.setenv("RENDER_GIT_COMMIT", "a" * 40)
    body = health.version()
    assert body["service"] == "cerebrum-blocks"
    assert body["git_sha"] == "a" * 40
    assert body["git_sha_short"] == "a" * 7


def test_an_unknown_sha_is_null_not_invented(monkeypatch):
    """Reported as unknown rather than guessed.

    A route that returns a plausible-looking wrong SHA is worse than one
    that returns nothing: the first is trusted.
    """
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    monkeypatch.delenv("GIT_COMMIT", raising=False)
    monkeypatch.setattr(health, "_build_sha", lambda: None)
    body = health.version()
    assert body["git_sha"] is None
    assert body["git_sha_short"] is None
    assert body["service"] == "cerebrum-blocks"


def test_the_sha_probe_never_raises(monkeypatch):
    """A broken git or a missing binary must not take the route down."""
    import subprocess

    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    monkeypatch.delenv("GIT_COMMIT", raising=False)

    def boom(*a, **k):
        raise OSError("git not found")

    monkeypatch.setattr(subprocess, "run", boom)
    assert health._sha_from_git() is None


def test_version_route_does_not_shell_out(monkeypatch):
    """The handler must not call subprocess — that belongs at import."""
    import subprocess

    monkeypatch.setenv("RENDER_GIT_COMMIT", "d" * 40)

    def boom(*a, **k):
        raise AssertionError("version() must not call subprocess.run")

    monkeypatch.setattr(subprocess, "run", boom)
    assert health.version()["git_sha"] == "d" * 40


def test_the_platform_env_wins_over_git(monkeypatch):
    """On Render the checkout may be shallow or absent; the env is truth."""
    monkeypatch.setenv("RENDER_GIT_COMMIT", "b" * 40)
    assert health._build_sha() == "b" * 40


def test_version_carries_no_secret_shaped_field(monkeypatch):
    """It is public, so it may only say what is safe to say publicly."""
    monkeypatch.setenv("RENDER_GIT_COMMIT", "c" * 40)
    body = health.version()
    assert set(body) == {"service", "git_sha", "git_sha_short", "env"}

