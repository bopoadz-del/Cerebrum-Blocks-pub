"""Tests for the neutral monitoring sub-kit."""

import pytest

from block_store.kits.universal_kernel.wave3.monitoring import (
    Metric,
    MetricsCollector,
    MetricsError,
)


def test_count_gauge_histogram():
    collector = MetricsCollector()
    collector.count("requests", {"route": "home"})
    collector.count("requests", {"route": "home"})
    collector.gauge("temperature", 22.5, {"zone": "a"})
    collector.histogram_observe("latency_ms", 12.0, {"route": "home"})

    text = collector.prometheus_format()
    assert "requests{route=\"home\"} 2" in text
    assert "temperature{zone=\"a\"} 22.5" in text
    assert "latency_ms_count{route=\"home\"} 1" in text


def test_invalid_metric_name():
    collector = MetricsCollector()
    with pytest.raises(MetricsError):
        collector.count("")
    with pytest.raises(MetricsError):
        collector.gauge("1metric", 1)


def test_capture_exception():
    collector = MetricsCollector()
    record = collector.capture_exception(ValueError("oops"), context={"route": "x"})
    assert record["type"] == "ValueError"
    assert collector.last_errors()[0]["message"] == "oops"


def test_metric_validates_name():
    with pytest.raises(MetricsError):
        Metric("bad name", 1)
