"""Honesty contracts for the core-infra cluster."""
import pytest

from app.blocks.migration import MigrationBlock
from app.blocks.health_check import HealthCheckBlock
from app.blocks.queue import QueueBlock
from app.blocks.config import ConfigBlock
from app.blocks.version import VersionBlock
from app.blocks.rate_limiter import RateLimiterBlock
from app.blocks.monitoring import MonitoringBlock


@pytest.mark.asyncio
async def test_migration_backup_refuses_without_id():
    block = MigrationBlock(None, {})
    created = await block._create_backup()
    assert created["status"] == "error"
    assert created["error"] == "migration backup not implemented"
    assert "backup_id" not in created
    restored = await block._restore_backup(created)
    assert restored["status"] == "error"
    assert "backup_id" not in restored


@pytest.mark.asyncio
async def test_health_check_unconfigured_apis_are_simulated():
    block = HealthCheckBlock(None, {})
    result = await block._check_external_apis()
    assert result["simulated"] is True
    assert result["healthy"] is False
    assert result["apis"] == {}


@pytest.mark.asyncio
async def test_queue_without_redis_url_is_in_process_and_says_so(monkeypatch):
    """No REDIS_URL: the deque backend, declared as such, with no Redis
    claim of any kind. (The Redis backend itself is covered by
    tests/blocks/test_queue.py on a fakeredis server.)"""
    monkeypatch.delenv("REDIS_URL", raising=False)
    block = QueueBlock(None, {})
    queued = await block._enqueue({"job_type": "noop", "queue": "default"})
    assert block.use_redis is False
    assert queued["backend"] == "memory"
    assert queued["persistence"] == "in_process"
    assert "redis" not in queued
    health = block.health()
    assert health["backend"] == "memory"
    assert health["persistence"] == "in_process"
    assert health["redis_configured"] is False
    assert health["redis_state"] == "not_configured"


@pytest.mark.asyncio
async def test_queue_names_an_unreachable_redis_instead_of_hiding_it(monkeypatch):
    """REDIS_URL set but Redis unreachable: fall back to memory and SAY so."""
    from app.core import redis_infra

    async def unreachable():
        return None

    monkeypatch.setenv("REDIS_URL", "redis://queue-honesty-test:6379/0")
    monkeypatch.setattr(redis_infra, "get_redis_client", unreachable)
    block = QueueBlock(None, {})
    queued = await block._enqueue({"job_type": "noop", "queue": "default"})
    assert block.use_redis is False
    assert queued["backend"] == "memory"
    assert queued["persistence"] == "in_process"
    assert queued["redis"] == "configured_but_unreachable"
    health = block.health()
    assert health["redis_configured"] is True
    assert health["redis_state"] == "configured_but_unreachable"


def test_config_does_not_claim_file_or_env_prefix():
    block = ConfigBlock(None, {})
    assert "config_file" not in block.default_config
    assert "env_prefix" not in block.default_config
    health = block.health()
    assert health["persistence"] == "in_process"
    assert health["config_file_read"] is False
    assert health["env_prefix_applied"] is False


def test_version_states_in_process_persistence():
    block = VersionBlock(None, {})
    health = block.health()
    assert health["persistence"] == "in_process"
    assert block.versions == {}


def test_rate_limiter_states_in_process_only():
    block = RateLimiterBlock(None, {})
    health = block.health()
    assert health["persistence"] == "in_process"
    assert "in-process only" in health["note"]
    assert block.counters == {}
    assert block.buckets == {}


def test_monitoring_add_provider_has_no_builtin_vendor():
    block = MonitoringBlock(None, {})
    assert block.providers == {}
    missing = block.add_provider("")
    assert missing["status"] == "error"
    added = block.add_provider("probe")
    assert added == {"status": "ok", "provider": "probe"}
    assert "kimi" not in block.providers
