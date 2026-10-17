"""Neutral metrics collection primitives."""

from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Tuple


class MetricsError(ValueError):
    """Raised when a metric operation is invalid."""


_NAME_RE = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")


def _validate_name(name: str) -> None:
    if not name or not _NAME_RE.match(name):
        raise MetricsError(f"invalid metric name: {name}")


@dataclass
class Metric:
    """A single metric observation."""

    name: str
    value: float
    labels: Dict[str, str] = field(default_factory=dict)
    timestamp: Optional[float] = None

    def __post_init__(self) -> None:
        _validate_name(self.name)
        if self.timestamp is None:
            self.timestamp = time.time()


class MetricsCollector:
    """In-process collector for counters, gauges, and histogram observations."""

    def __init__(self, max_errors: int = 10) -> None:
        self._counters: Dict[str, Dict[FrozenSet[Tuple[str, str]], int]] = {}
        self._gauges: Dict[str, Dict[FrozenSet[Tuple[str, str]], float]] = {}
        self._histograms: Dict[str, Dict[FrozenSet[Tuple[str, str]], List[float]]] = {}
        self._errors: deque = deque(maxlen=max_errors)

    @staticmethod
    def _label_key(labels: Optional[Dict[str, str]]) -> FrozenSet[Tuple[str, str]]:
        return frozenset((labels or {}).items())

    def count(
        self,
        name: str,
        labels: Optional[Dict[str, str]] = None,
        delta: int = 1,
    ) -> Metric:
        """Increment a counter."""
        _validate_name(name)
        key = self._label_key(labels)
        self._counters.setdefault(name, {})
        self._counters[name][key] = self._counters[name].get(key, 0) + delta
        return Metric(name, float(self._counters[name][key]), labels or {})

    def gauge(
        self,
        name: str,
        value: float,
        labels: Optional[Dict[str, str]] = None,
    ) -> Metric:
        """Record a gauge value."""
        _validate_name(name)
        key = self._label_key(labels)
        self._gauges.setdefault(name, {})
        self._gauges[name][key] = float(value)
        return Metric(name, float(value), labels or {})

    def histogram_observe(
        self,
        name: str,
        value: float,
        labels: Optional[Dict[str, str]] = None,
    ) -> Metric:
        """Observe a value in a histogram."""
        _validate_name(name)
        key = self._label_key(labels)
        self._histograms.setdefault(name, {})
        self._histograms[name].setdefault(key, []).append(float(value))
        return Metric(name, float(value), labels or {})

    @staticmethod
    def _format_labels(label_items: FrozenSet[Tuple[str, str]]) -> str:
        if not label_items:
            return ""
        pairs = sorted(label_items)
        return "{" + ",".join(f'{k}="{v}"' for k, v in pairs) + "}"

    def prometheus_format(self) -> str:
        """Render metrics in basic OpenMetrics text format."""
        lines: List[str] = []

        for name, series in sorted(self._counters.items()):
            lines.append(f"# TYPE {name} counter")
            for key, value in sorted(series.items(), key=lambda kv: sorted(kv[0])):
                lines.append(f"{name}{self._format_labels(key)} {value}")

        for name, series in sorted(self._gauges.items()):
            lines.append(f"# TYPE {name} gauge")
            for key, value in sorted(series.items(), key=lambda kv: sorted(kv[0])):
                lines.append(f"{name}{self._format_labels(key)} {value}")

        for name, series in sorted(self._histograms.items()):
            lines.append(f"# TYPE {name} histogram")
            for key, values in sorted(series.items(), key=lambda kv: sorted(kv[0])):
                labels = self._format_labels(key)
                for value in values:
                    lines.append(f"{name}{labels} {value}")
                lines.append(f"{name}_sum{labels} {sum(values)}")
                lines.append(f"{name}_count{labels} {len(values)}")

        return "\n".join(lines)

    def capture_exception(
        self,
        error: Exception,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Store the last N exceptions for debugging."""
        record = {
            "type": type(error).__name__,
            "message": str(error),
            "context": context or {},
            "timestamp": time.time(),
        }
        self._errors.append(record)
        return record

    def last_errors(self, n: int = 10) -> List[Dict[str, Any]]:
        """Return the last N captured errors."""
        return list(self._errors)[-n:]
