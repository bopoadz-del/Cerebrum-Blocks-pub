"""Neutral health probe primitives."""

from __future__ import annotations

from typing import Any, Callable, Dict, List


HealthCheckFn = Callable[[], Dict[str, Any]]


class HealthProbe:
    """A single named health probe."""

    def __init__(
        self,
        name: str,
        check_fn: HealthCheckFn,
        critical: bool = True,
    ) -> None:
        self.name = name
        self.check_fn = check_fn
        self.critical = critical

    def run(self) -> Dict[str, Any]:
        try:
            result = self.check_fn()
        except Exception as exc:
            result = {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}
        return {
            "name": self.name,
            "ok": bool(result.get("ok", False)),
            "status": result.get("status", "unknown"),
            "detail": result.get("detail", ""),
            "critical": self.critical,
        }


class HealthRegistry:
    """Registry of health probes with aggregate status."""

    def __init__(self, version: str = "0.1.0") -> None:
        self._probes: List[HealthProbe] = []
        self.version = version
        self._built_in_registered = False

    def register(self, probe: HealthProbe) -> None:
        """Register a probe."""
        self._probes.append(probe)

    def _built_in_check(self, name: str) -> Dict[str, Any]:
        """Neutral stub for optional dependencies: reports unknown, not failure."""
        return {
            "ok": True,
            "status": "unknown",
            "detail": f"{name} not configured",
        }

    def register_builtin_probes(self) -> None:
        """Register identity_store, audit_chain, and vector_store probes."""
        self.register(
            HealthProbe(
                "identity_store",
                lambda: self._built_in_check("identity_store"),
            )
        )
        self.register(
            HealthProbe(
                "audit_chain",
                lambda: self._built_in_check("audit_chain"),
            )
        )
        self.register(
            HealthProbe(
                "vector_store",
                lambda: self._built_in_check("vector_store"),
            )
        )
        self._built_in_registered = True

    def run_checks(self) -> Dict[str, Any]:
        """Run all probes and return an aggregate health report.

        Returns overall ``healthy`` only when every critical probe passes.
        """
        if not self._built_in_registered:
            self.register_builtin_probes()

        checks = [probe.run() for probe in self._probes]
        unhealthy = any(
            not check["ok"] and check["critical"] for check in checks
        )
        return {
            "status": "unhealthy" if unhealthy else "healthy",
            "checks": checks,
            "version": self.version,
        }
