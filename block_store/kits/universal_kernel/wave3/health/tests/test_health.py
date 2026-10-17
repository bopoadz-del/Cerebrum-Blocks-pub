"""Tests for the neutral health probe sub-kit."""

from block_store.kits.universal_kernel.wave3.health import HealthProbe, HealthRegistry


def test_health_registry_register_run():
    registry = HealthRegistry(version="0.2.0")
    registry.register(HealthProbe("db", lambda: {"ok": True, "detail": "up"}))
    report = registry.run_checks()
    assert report["status"] == "healthy"
    assert report["version"] == "0.2.0"
    assert any(c["name"] == "db" and c["ok"] for c in report["checks"])


def test_builtin_probes_are_registered():
    registry = HealthRegistry()
    report = registry.run_checks()
    names = {c["name"] for c in report["checks"]}
    assert {"identity_store", "audit_chain", "vector_store"} <= names


def test_builtin_probes_report_unknown_when_not_configured():
    registry = HealthRegistry()
    report = registry.run_checks()
    for check in report["checks"]:
        if check["name"] in {"identity_store", "audit_chain", "vector_store"}:
            assert check["status"] == "unknown"
            assert check["ok"] is True


def test_critical_failure_makes_unhealthy():
    registry = HealthRegistry()
    registry.register(
        HealthProbe("bad", lambda: {"ok": False, "detail": "down"}, critical=True)
    )
    report = registry.run_checks()
    assert report["status"] == "unhealthy"


def test_non_critical_failure_stays_healthy():
    registry = HealthRegistry()
    registry.register(
        HealthProbe("warn", lambda: {"ok": False, "detail": "slow"}, critical=False)
    )
    report = registry.run_checks()
    assert report["status"] == "healthy"


def test_probe_exception_is_failure():
    registry = HealthRegistry()
    registry.register(HealthProbe("explode", lambda: (_ for _ in ()).throw(RuntimeError("boom"))))
    report = registry.run_checks()
    bad = next(c for c in report["checks"] if c["name"] == "explode")
    assert bad["ok"] is False
    assert report["status"] == "unhealthy"
