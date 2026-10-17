"""Config injection and the fallback ladder, proved on CacheManager.

KERNEL_DEFAULTS 1.5. Two claims.

**A block reads what it was handed.** No ``os.getenv`` in block code. The
consequence that matters is testability: the Redis-present path below is
exercised with no Redis server anywhere, because the client is injected
rather than fetched from a module-level singleton that reads the environment.

**Every external dependency has a local fallback, and taking it is visible.**
Degrading is legitimate. Degrading quietly is not -- serving from an
in-process dict while the caller believes it is talking to Redis is how a
cache works in testing and loses every write in production.
"""

from __future__ import annotations

import asyncio

import pytest

from app.blocks.cache_manager import CacheManagerBlock
from app.core.block_config import (
    FALLBACK_LADDER,
    LADDER_BY_DEPENDENCY,
    Config,
    MissingSetting,
    fallback_note,
)


def run(coro):
    return asyncio.run(coro)


# -- Config ----------------------------------------------------------------


def test_a_block_reads_what_it_was_handed():
    config = Config({"default_ttl": 60})
    assert config.get("default_ttl") == 60
    assert config.get("absent") is None
    assert config.get("absent", "fallback") == "fallback"


def test_an_override_sits_on_top_of_a_default_without_either_knowing():
    platform = Config({"default_ttl": 3600, "cache_backend": "redis"})
    block = platform.child(default_ttl=60)

    assert block.get("default_ttl") == 60
    assert block.get("cache_backend") == "redis"
    assert platform.get("default_ttl") == 3600, "the child mutated its parent"


def test_a_missing_required_setting_names_itself():
    """'KeyError: x' three frames deep in a pipeline tells a reader nothing
    about which block needed what."""
    with pytest.raises(MissingSetting) as excinfo:
        Config({}).require("REDIS_URL")

    assert "REDIS_URL" in str(excinfo.value)
    assert "handed its settings" in str(excinfo.value)


def test_from_env_takes_an_explicit_mapping_so_a_test_never_mutates_os_environ():
    config = Config.from_env({"REDIS_URL": "redis://x", "NOISE": "1"}, keys=["REDIS_URL"])

    assert config.get("REDIS_URL") == "redis://x"
    assert config.get("NOISE") is None, "an unnamed key was lifted anyway"


def test_naming_the_keys_makes_a_blocks_dependencies_readable():
    everything = Config.from_env({"A": "1", "B": "2"})
    assert set(everything.as_dict()) == {"A", "B"}


def test_as_dict_merges_parent_then_child():
    parent = Config({"a": 1, "b": 2})
    assert parent.child(b=3).as_dict() == {"a": 1, "b": 3}


def test_membership_walks_to_the_parent():
    parent = Config({"a": 1})
    assert "a" in parent.child(b=2)
    assert "missing" not in parent.child(b=2)


# -- the ladder ------------------------------------------------------------


def test_the_ladder_covers_the_four_dependencies_the_spec_names():
    assert set(LADDER_BY_DEPENDENCY) == {"cache", "database", "objects", "llm"}


@pytest.mark.parametrize("rung", FALLBACK_LADDER, ids=lambda r: r.dependency)
def test_every_rung_names_a_preferred_and_a_fallback(rung):
    assert rung.preferred and rung.fallback
    assert rung.preferred != rung.fallback
    assert rung.note.strip()


def test_the_llm_fallback_refuses_rather_than_answering():
    """The rung most easily got wrong. A fallback that answers anyway turns
    'this platform has no LLM' into 'this platform is confidently wrong'."""
    llm = LADDER_BY_DEPENDENCY["llm"]

    assert llm.fallback == "refuse"
    assert "confidently wrong" in llm.note


def test_a_note_on_the_preferred_rung_is_not_an_apology():
    assert fallback_note("cache", "redis") == "cache: redis"


def test_a_note_on_a_fallback_rung_says_what_was_given_up():
    note = fallback_note("cache", "memory")

    assert "fell back" in note
    assert "redis" in note
    assert "Lost on restart" in note


def test_an_unknown_dependency_still_produces_a_line_rather_than_a_crash():
    assert "queue" in fallback_note("queue", "memory")


# -- CacheManager: Redis ABSENT -------------------------------------------


def _scope(key, **extra):
    """A cache payload that carries the load-bearing scope fields."""
    payload = {
        "key": key,
        "tenant_id": extra.pop("tenant_id", "tenant-a"),
        "project_id": extra.pop("project_id", "project-1"),
        "source_class": extra.pop("source_class", "official_guidance"),
    }
    payload.update(extra)
    return payload


def _memory_block():
    """The fallback rung, pinned. No environment involved."""
    return CacheManagerBlock(config={"cache_backend": "memory"})


def test_with_no_redis_the_local_fallback_is_reachable():
    """#87 restated as an injected test rather than an environmental one."""
    block = _memory_block()
    assert block._redis is None

    setter = run(block.set(_scope("k", value="hello"), {}))
    assert setter["status"] == "success"

    getter = run(block.get(_scope("k"), {}))
    assert getter["status"] == "success"
    assert getter["found"] is True
    assert getter["value"] == "hello"


def test_the_memory_rung_says_it_is_the_memory_rung():
    health = run(_memory_block().health_check())

    assert health["backend"] == "memory"
    assert health["redis_connected"] is False
    assert "fell back" in health["note"]


def test_delete_and_exists_work_on_the_local_rung():
    block = _memory_block()
    run(block.set(_scope("k", value=1), {}))

    assert run(block.exists(_scope("k"), {}))["exists"] is True
    assert run(block.delete(_scope("k"), {}))["deleted"] is True
    assert run(block.exists(_scope("k"), {}))["exists"] is False


def test_stats_on_the_local_rung_names_the_fallback():
    block = _memory_block()
    run(block.set(_scope("k", value=1), {}))
    stats = run(block.stats())

    assert stats["backend"] == "local"
    assert stats["entries"] == 1
    assert "fell back" in stats["note"]


# -- CacheManager: Redis PRESENT ------------------------------------------


class _FakeRedis:
    """Enough Redis to prove the branch is taken. Injected, not patched."""

    def __init__(self):
        self.store = {}
        self.calls = []

    def get(self, key):
        self.calls.append(("get", key))
        return self.store.get(key)

    def setex(self, key, ttl, value):
        self.calls.append(("setex", key, ttl))
        self.store[key] = value

    def delete(self, key):
        self.calls.append(("delete", key))
        return 1 if self.store.pop(key, None) is not None else 0

    def exists(self, key):
        return 1 if key in self.store else 0

    def flushdb(self):
        self.store.clear()

    def dbsize(self):
        return len(self.store)

    def info(self):
        return {"used_memory_human": "1.00M"}


def _redis_block():
    """The preferred rung, with no Redis server anywhere.

    This is the payoff of injection: before it, reaching this path needed a
    live server or a monkeypatched module global.
    """
    client = _FakeRedis()
    return CacheManagerBlock(config={"redis_client": client}), client


def test_with_redis_present_the_redis_branch_is_taken():
    block, client = _redis_block()
    assert block._redis is client

    run(block.set(_scope("k", value="hello"), {}))
    assert any(call[0] == "setex" for call in client.calls), "Redis was not written to"

    getter = run(block.get(_scope("k"), {}))
    assert getter["found"] is True
    assert getter["value"] == "hello"


def test_with_redis_present_nothing_is_written_to_the_local_cache():
    """The two rungs must not both be live: a write that lands in memory and
    is read back from memory looks identical to a working cache."""
    block, _ = _redis_block()
    run(block.set(_scope("k", value="hello"), {}))

    assert block._local_cache == {}


def test_the_redis_rung_says_it_is_the_redis_rung():
    block, _ = _redis_block()
    health = run(block.health_check())

    assert health["backend"] == "redis"
    assert health["redis_connected"] is True
    assert health["note"] == "cache: redis"


def test_stats_reports_the_redis_backend():
    block, _ = _redis_block()
    run(block.set(_scope("k", value=1), {}))
    stats = run(block.stats())

    assert stats["backend"] == "redis"
    assert stats["keys"] == 1


def test_a_broken_redis_is_reported_rather_than_silently_served_from_memory():
    """The dangerous fallback. If Redis errors and the block quietly answers
    from its local dict, the caller is told the cache is fine."""

    class _Broken(_FakeRedis):
        def get(self, key):
            raise ConnectionError("connection refused")

    block = CacheManagerBlock(config={"redis_client": _Broken()})
    result = run(block.get(_scope("k"), {}))

    assert result["status"] == "error"
    assert "connection refused" in result["error"]


# -- the non-breaking guarantee -------------------------------------------


def test_an_unconfigured_block_still_uses_the_shared_factory(monkeypatch):
    """What every existing caller does. The default path is unchanged: no
    config, no injection, same shared factory as before this PR."""
    called = []

    def _factory():
        called.append(True)
        return None

    monkeypatch.setattr(
        "app.blocks.cache_manager.get_sync_redis_client", _factory
    )
    block = CacheManagerBlock()

    assert block._redis is None
    assert called, "the shared factory was not consulted"


def test_the_settings_view_follows_config_edited_after_construction():
    block = CacheManagerBlock()
    assert block.settings.get("cache_backend") is None

    block.config["cache_backend"] = "memory"
    assert block.settings.backend("cache") == "memory"
    assert block._redis is None


def test_this_module_does_not_reach_for_the_environment():
    """The rule, asserted against the reference implementation's SYNTAX.

    Parsed rather than grepped: the module's own docstring explains that it
    does not call ``os.getenv``, and a substring search cannot tell that
    sentence apart from the call it forbids.
    """
    import ast
    from pathlib import Path as _Path

    import app.blocks.cache_manager as module

    tree = ast.parse(_Path(module.__file__).read_text(encoding="utf-8"))
    reaches = [
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "os"
        and node.attr in ("getenv", "environ")
    ]
    assert reaches == [], "block code reached for the environment: %s" % reaches


# -- scope keys: tenant / project / source class --------------------------


def test_scope_key_carries_tenant_project_and_source_class():
    block = _memory_block()
    key = block.scope_key("secret", "tenant-a", "project-1", "official_guidance")

    assert "tenant-a" in key
    assert "project-1" in key
    assert "official_guidance" in key
    assert "secret" in key
    assert key != "secret"


def test_cross_tenant_hit_is_impossible():
    block = _memory_block()
    run(block.set(_scope("secret", value="alpha-only"), {}))

    other = run(
        block.get(
            _scope("secret", tenant_id="tenant-b"),
            {},
        )
    )
    assert other["status"] == "success"
    assert other["found"] is False


def test_cross_source_class_hit_is_impossible():
    block = _memory_block()
    run(block.set(_scope("secret", value="regulator-only", source_class="regulator"), {}))

    other = run(block.get(_scope("secret", source_class="contributor_unverified"), {}))
    assert other["found"] is False


def test_a_bare_key_is_refused_rather_than_written_unscoped():
    block = _memory_block()
    result = run(block.set({"key": "secret", "value": "leak"}, {}))

    assert result["status"] == "error"
    assert "scope" in result["error"].lower()
    assert block._local_cache == {}


def test_mutation_probe_dropping_tenant_from_the_key_would_leak():
    """The same scope-key test as the isolation contract: if the on-wire
    key were only the logical name, tenant B would read tenant A's value.

    This is the mutation. The real resolver must not be that formula, and
    the leak must be demonstrable on the mutated one so a later edit that
    'simplifies' the key is caught by the difference.
    """
    block = _memory_block()
    run(block.set(_scope("secret", value="alpha-only"), {}))

    scoped = block.scope_key("secret", "tenant-a", "project-1", "official_guidance")
    assert scoped in block._local_cache
    assert "secret" not in block._local_cache, (
        "the logical name was stored unscoped; that is the cross-tenant leak"
    )

    mutated = "secret"
    assert mutated != scoped
    # A cache that keyed on the mutated form would return tenant A's value
    # to anyone who asked for the same logical name.
    assert block._local_cache[scoped]["value"] == "alpha-only"
    assert mutated not in block._local_cache
