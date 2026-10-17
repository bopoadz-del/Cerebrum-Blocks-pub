#!/usr/bin/env python3
import sys
import asyncio
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.blocks import BLOCK_REGISTRY

async def test_block(name, block_class):
    try:
        if callable(block_class):
            block = block_class()
        else:
            block = block_class
        
        has_process = hasattr(block, 'process')
        has_execute = hasattr(block, 'execute')
        
        try:
            result = await block.execute({"action": "status"}, {})
            status = "✅ WORKING"
            detail = f"Returns: {list(result.keys())[:5]}"
        except Exception as e:
            error_msg = str(e)
            if "not implemented" in error_msg.lower():
                status = "⚠️  STUB"
                detail = "Method not implemented"
            elif "module" in error_msg.lower() or "import" in error_msg.lower():
                status = "❌ MISSING_DEP"
                detail = error_msg[:80]
            else:
                status = "⚠️  ERROR"
                detail = error_msg[:80]
        
        return {"name": name, "status": status, "detail": detail}
    except Exception as e:
        return {"name": name, "status": "❌ BROKEN", "detail": str(e)[:80]}

async def main():
    print("="*80)
    print("AUDITING ALL BLOCKS")
    print("="*80 + "\n")
    
    results = []
    for name, block_class in BLOCK_REGISTRY.items():
        result = await test_block(name, block_class)
        results.append(result)
    
    working = [r for r in results if r["status"] == "✅ WORKING"]
    stubs = [r for r in results if r["status"] == "⚠️  STUB"]
    errors = [r for r in results if r["status"] == "⚠️  ERROR"]
    missing_deps = [r for r in results if r["status"] == "❌ MISSING_DEP"]
    broken = [r for r in results if r["status"] == "❌ BROKEN"]
    
    print(f"WORKING: {len(working)}/{len(results)}")
    for r in working:
        print(f"  ✅ {r['name']:25} - {r['detail']}")
    
    print(f"\nSTUBS: {len(stubs)}")
    for r in stubs:
        print(f"  ⚠️  {r['name']:25} - {r['detail']}")
    
    print(f"\nERRORS: {len(errors)}")
    for r in errors:
        print(f"  ⚠️  {r['name']:25} - {r['detail']}")
    
    print(f"\nMISSING DEPENDENCIES: {len(missing_deps)}")
    for r in missing_deps:
        print(f"  ❌ {r['name']:25} - {r['detail']}")
    
    print(f"\nBROKEN: {len(broken)}")
    for r in broken:
        print(f"  ❌ {r['name']:25} - {r['detail']}")
    
    print("\n" + "="*80)
    print(f"SUMMARY: {len(working)} working, {len(stubs)} stubs, {len(errors)} errors, {len(missing_deps)} missing deps, {len(broken)} broken")
    print("="*80)

if __name__ == "__main__":
    asyncio.run(main())
