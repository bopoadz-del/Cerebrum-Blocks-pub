#!/usr/bin/env python3
"""Test Memory and Monitoring Blocks."""

import asyncio
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from app.blocks import MemoryBlock, MonitoringBlock


@pytest.mark.asyncio
async def test_memory_block():
    """Test Memory Block functionality."""
    print("\n" + "="*60)
    print("🧠 TESTING MEMORY BLOCK")
    print("="*60)

    memory = MemoryBlock(None, {"max_size": 1000, "default_ttl": 60})
    await memory._legacy_initialize()

    # Test SET
    print("\n1. Testing SET...")
    result = await memory.process({
        "action": "set",
        "key": "test_key",
        "value": {"message": "Hello from Memory Block!"},
        "ttl": 300
    }, {"action": "set"})
    print(f"   Set result: {result}")
    assert result["stored"] == True, "SET failed"

    # Test GET (hit)
    print("\n2. Testing GET (cache hit)...")
    result = await memory.process({
        "action": "get",
        "key": "test_key"
    }, {"action": "get"})
    print(f"   Get result: {result}")
    assert result["hit"] == True, "GET should be a hit"
    assert result["value"]["message"] == "Hello from Memory Block!", "Value mismatch"

    # Test GET (miss)
    print("\n3. Testing GET (cache miss)...")
    result = await memory.process({
        "action": "get",
        "key": "nonexistent_key"
    }, {"action": "get"})
    print(f"   Get result: {result}")
    assert result["hit"] == False, "GET should be a miss"

    # Test STATS
    print("\n4. Testing STATS...")
    result = await memory.process({"action": "stats"}, {"action": "stats"})
    print(f"   Stats: {result}")
    assert result["hits"] == 1, "Should have 1 hit"
    assert result["misses"] == 1, "Should have 1 miss"

    # Test EXISTS
    print("\n5. Testing EXISTS...")
    result = await memory.process({
        "action": "exists",
        "key": "test_key"
    }, {"action": "exists"})
    print(f"   Exists result: {result}")
    assert result["exists"] == True, "Key should exist"

    # Test KEYS
    print("\n6. Testing KEYS...")
    result = await memory.process({"action": "keys"}, {"action": "keys"})
    print(f"   Keys result: {result}")
    assert "test_key" in result["keys"], "test_key should be in keys"

    # Test DELETE
    print("\n7. Testing DELETE...")
    result = await memory.process({
        "action": "delete",
        "key": "test_key"
    }, {"action": "delete"})
    print(f"   Delete result: {result}")
    assert result["deleted"] == True, "DELETE should succeed"

    # Verify deletion
    result = await memory.process({
        "action": "get",
        "key": "test_key"
    }, {"action": "get"})
    assert result["hit"] == False, "Key should be deleted"

    print("\n✅ Memory Block tests PASSED!")
    return True


@pytest.mark.asyncio
async def test_monitoring_block():
    """Test Monitoring Block functionality."""
    print("\n" + "="*60)
    print("📊 TESTING MONITORING BLOCK")
    print("="*60)

    memory = MemoryBlock(None, {"max_size": 1000, "default_ttl": 3600})
    await memory._legacy_initialize()

    monitoring = MonitoringBlock(None, {})
    monitoring.memory_block = memory
    await monitoring._legacy_initialize()

    for name in ("deepseek", "groq", "openai"):
        added = monitoring.add_provider(name)
        assert added["status"] == "ok", added

    # Simulate some calls
    print("\n1. Simulating provider calls...")

    # DeepSeek - good performance
    await monitoring.process({
        "action": "record_call",
        "provider": "deepseek",
        "latency_ms": 800,
        "success": True
    }, {"action": "record_call"})
    await monitoring.process({
        "action": "record_call",
        "provider": "deepseek",
        "latency_ms": 750,
        "success": True
    }, {"action": "record_call"})

    # DeepSeek - one failure
    await monitoring.process({
        "action": "record_call",
        "provider": "deepseek",
        "latency_ms": 5000,
        "success": False,
        "error_type": "timeout"
    }, {"action": "record_call"})

    # Groq - excellent performance
    await monitoring.process({
        "action": "record_call",
        "provider": "groq",
        "latency_ms": 120,
        "success": True
    }, {"action": "record_call"})
    await monitoring.process({
        "action": "record_call",
        "provider": "groq",
        "latency_ms": 95,
        "success": True
    }, {"action": "record_call"})
    await monitoring.process({
        "action": "record_call",
        "provider": "groq",
        "latency_ms": 110,
        "success": True
    }, {"action": "record_call"})

    # OpenAI - slower
    await monitoring.process({
        "action": "record_call",
        "provider": "openai",
        "latency_ms": 2500,
        "success": True
    }, {"action": "record_call"})

    print("   Recorded 6 calls across 3 providers")

    # Test LEADERBOARD
    print("\n2. Testing LEADERBOARD...")
    lb = await monitoring.process({"action": "leaderboard"}, {"action": "leaderboard"})
    print(f"   Generated at: {lb['generated_at']}")
    print(f"   Top provider: {lb['top_provider']}")
    print("\n   📊 Provider Rankings:")
    for entry in lb["leaderboard"]:
        emoji = "🥇" if entry["rank"] == 1 else "🥈" if entry["rank"] == 2 else "🥉" if entry["rank"] == 3 else "  "
        print(f"   {emoji} #{entry['rank']} {entry['name']}: {entry['reliability_score']}% ({entry['status']}) - {entry['avg_latency_ms']}ms avg")

    # Test RECOMMEND
    print("\n3. Testing RECOMMEND...")
    rec = await monitoring.process({"action": "recommend"}, {"action": "recommend"})
    print(f"   Recommended: {rec['recommended']}")
    print(f"   Confidence: {rec['confidence']}%")
    print(f"   Reason: {rec['reason']}")
    print(f"   Fallback sequence: {rec.get('fallback_sequence', [])}")

    # Test PREDICTIVE ANALYSIS
    print("\n4. Testing PREDICTIVE ANALYSIS...")
    pred = await monitoring.process({"action": "predictive_failover"}, {"action": "predictive_failover"})
    print(f"   Predictions: {len(pred['predictions'])}")
    if pred['predictions']:
        for p in pred['predictions']:
            print(f"   ⚠️  {p['provider']}: {p['prediction']} ({p['severity']})")
    else:
        print("   ✅ No issues predicted")

    # Test HEALTH REPORT
    print("\n5. Testing HEALTH REPORT...")
    health = await monitoring.process({"action": "health_report"}, {"action": "health_report"})
    print(f"   Overall status: {health['overall_status']}")
    print(f"   Failover readiness: {health['failover_readiness']}")

    # Test PROVIDER STATUS
    print("\n6. Testing PROVIDER STATUS...")
    status = await monitoring.process({
        "action": "provider_status",
        "provider": "deepseek"
    }, {"action": "provider_status"})
    assert "reliability_score" in status, status
    assert status["provider"] == "deepseek"
    print(f"   {status['provider']} reliability: {status['reliability_score']}%")

    unknown = await monitoring.process({
        "action": "provider_status",
        "provider": "a-provider-nobody-configured"
    }, {"action": "provider_status"})
    assert unknown.get("error") == "Unknown provider", unknown
    assert "reliability_score" not in unknown, (
        "an unknown provider must not be given a score"
    )
    print("   unknown provider -> reported, not scored")

    print("\n✅ Monitoring Block tests PASSED!")
    return True


async def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("🔥 CEREBRUM BLOCKS - MEMORY & MONITORING TEST SUITE")
    print("="*60)

    try:
        await test_memory_block()
        await test_monitoring_block()

        print("\n" + "="*60)
        print("🎉 ALL TESTS PASSED!")
        print("="*60)
        print("\n📦 New Blocks Ready:")
        print("   • Memory Block: High-speed cache with TTL + LRU eviction")
        print("   • Monitoring Block: Provider leaderboard & predictive failover")
        print("\n🔌 New API Endpoints:")
        print("   GET  /v1/leaderboard      - Provider reliability rankings")
        print("   GET  /v1/recommend        - AI-powered provider selection")
        print("   GET  /v1/predict          - Predictive failure analysis")
        print("   GET  /v1/system/health    - Full system health report")
        print("   GET  /v1/memory/stats     - Cache statistics")
        print("   POST /v1/memory/{action}  - Cache operations (get/set/delete)")
        return 0

    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(asyncio.run(main()))
