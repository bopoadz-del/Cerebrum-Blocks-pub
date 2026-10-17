#!/usr/bin/env python3
"""PROPER TEST: Structural integrity + graceful error handling."""
import sys, asyncio

import pytest

sys.path.insert(0, '.')
from app.blocks import BLOCK_REGISTRY

pytestmark = pytest.mark.manual_script

async def test_block(name, block_class):
    errors = []
    
    try:
        block = block_class()
    except Exception as e:
        return False, f"INIT CRASH: {type(e).__name__}: {e}"
    
    # 1. process() exists and callable
    if not hasattr(block, 'process') or not callable(getattr(block, 'process')):
        errors.append("missing process()")
    
    # 2. execute() exists and callable
    if not hasattr(block, 'execute') or not callable(getattr(block, 'execute')):
        errors.append("missing execute()")
    
    # 3. execute() returns standardized dict without crashing
    try:
        result = await block.execute({"action": "status"}, {})
    except Exception as e:
        errors.append(f"execute() CRASH: {type(e).__name__}: {e}")
        result = None
    
    # 4. Result structure check
    if result is not None:
        if not isinstance(result, dict):
            errors.append(f"execute() returned {type(result).__name__}, not dict")
        else:
            required_keys = ['status', 'block']
            missing = [k for k in required_keys if k not in result]
            if missing:
                errors.append(f"missing keys: {missing}")
            
            # 5. If error, check it's graceful (not a code crash)
            if result.get('status') == 'error':
                err_text = str(result.get('result', ''))
                crash_indicators = ['traceback', 'attributeerror', 'nameerror', 'importerror', 'keyerror', 'typeerror', 'indexerror']
                if any(x in err_text.lower() for x in crash_indicators):
                    errors.append(f"error contains code crash: {err_text[:80]}")
    
    if errors:
        return False, "; ".join(errors)
    return True, "structurally sound"

async def main():
    print("="*80)
    print("PROPER TEST: Structure + Graceful Errors (no API keys/files needed)")
    print("="*80 + "\n")
    
    passed = 0
    failed = 0
    
    for name, block_class in sorted(BLOCK_REGISTRY.items()):
        ok, detail = await test_block(name, block_class)
        status = "✅ PASS" if ok else "❌ FAIL"
        print(f"{status} {name:30} {detail}")
        if ok:
            passed += 1
        else:
            failed += 1
    
    print(f"\n{'='*80}")
    print(f"RESULTS: {passed} structurally sound, {failed} broken out of {passed+failed}")
    print(f"{'='*80}")
    
    if failed == 0:
        print("\n🎉 ALL BLOCKS STRUCTURALLY SOUND — they handle missing deps gracefully")
        print("   (Blocks returning 'error' status = missing API key / file / dependency)")
        print("   This is EXPECTED in a test environment without real credentials.")

if __name__ == "__main__":
    asyncio.run(main())
