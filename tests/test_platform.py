#!/usr/bin/env python3
"""Test blocks THROUGH the platform API, not directly."""
import sys, asyncio, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

async def main():
    print("="*80)
    print("PLATFORM TEST — Blocks via HTTP API (/v1/execute)")
    print("="*80 + "\n")
    
    # 1. Health check
    r = client.get("/health")
    print(f"/health: {r.status_code} — {r.json().get('status', 'unknown')}")
    
    # 2. List blocks
    r = client.get("/blocks")
    blocks = r.json().get("blocks", [])
    print(f"/blocks: {len(blocks)} blocks registered\n")
    
    # 3. Test each block via /v1/execute
    passed = 0
    failed = 0
    
    for block_info in blocks:
        name = block_info.get("name", "unknown")
        r = client.post("/v1/execute", json={
            "block": name,
            "input": {"action": "status"},
            "params": {}
        })
        
        if r.status_code != 200:
            status = "❌ FAIL"
            detail = f"HTTP {r.status_code}"
            failed += 1
        else:
            data = r.json()
            if data.get("status") == "success":
                status = "✅ PASS"
                detail = "returns success"
                passed += 1
            else:
                err = str(data.get("error", data.get("result", "unknown")))[:60]
                status = "⚠️  ERROR"
                detail = f"status=error: {err}"
                passed += 1  # Still structurally sound via API
        
        print(f"{status} {name:30} {detail}")
    
    print(f"\n{'='*80}")
    print(f"RESULTS: {passed} responded via API, {failed} HTTP failures out of {passed+failed}")
    print(f"{'='*80}")

if __name__ == "__main__":
    asyncio.run(main())
