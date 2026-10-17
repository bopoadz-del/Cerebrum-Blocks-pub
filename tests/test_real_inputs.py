#!/usr/bin/env python3
"""Test every block with REAL correct inputs (not "status")."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.blocks import BLOCK_REGISTRY

# Real inputs matched to each block's actual schema
TEST_INPUTS = {
    "chat":       {"input": {"message": "What is concrete curing time?"}, "params": {}},
    "pdf":        {"input": {"text": "This is a sample PDF text content."}, "params": {"action": "extract_text"}},
    "pdf_v2":     {"input": {"text": "This is a sample PDF text content."}, "params": {"action": "extract_text"}},
    "ocr":        {"input": {"text": "Sample OCR text from image."}, "params": {"action": "extract"}},
    "ocr_v2":     {"input": {"text": "Sample OCR text from image."}, "params": {"action": "extract"}},
    "image":      {"input": {"prompt": "construction site safety diagram"}, "params": {}},
    "document_engine": {"input": {"text": "Building specifications document."}, "params": {"action": "process"}},
    "translate":  {"input": {"text": "Hello world", "target": "ar"}, "params": {}},
    "voice":      {"input": {"text": "Construction safety reminder"}, "params": {"action": "tts"}},
    "web":        {"input": {"url": "https://example.com"}, "params": {"action": "scrape"}},
    "construction": {"input": {"text": "Building area: 1500 m2. Concrete: 300 m3."}, "params": {"action": "auto_pipeline"}},
    "construction_v2": {"input": {"text": "Building area: 1500 m2. Concrete: 300 m3."}, "params": {"action": "auto_pipeline"}},
    "boq_processor": {"input": {"text": "Concrete 300 m3, Steel 45 tons"}, "params": {"action": "process_boq"}},
    "bim":        {"input": {"text": "IFC model data"}, "params": {"action": "status"}},
    "bim_extractor": {"input": {"file_path": "/tmp/test.ifc"}, "params": {"action": "extract"}},
    "drawing_qto": {"input": {"file_path": "/tmp/test.pdf"}, "params": {"action": "extract_quantities"}},
    "primavera_parser": {"input": {"file_path": "/tmp/test.xer"}, "params": {"action": "parse"}},
    "spec_analyzer": {"input": {"text": "Material: Concrete grade C30"}, "params": {"action": "analyze"}},
    "formula_executor": {"input": {"expression": "300 * 45"}, "params": {}},
    "sympy_reasoning": {"input": {"expression": "solve(x**2 - 4, x)"}, "params": {}},
    "historical_benchmark": {"input": {"text": "Compare concrete costs"}, "params": {"action": "benchmark"}},
    "smart_orchestrator": {"input": {"text": "Process this document"}, "params": {"action": "route"}},
    "local_drive": {"input": {"path": "/tmp"}, "params": {"action": "list"}},
    "google_drive": {"input": {"action": "list"}, "params": {}},
    "onedrive":   {"input": {"action": "list"}, "params": {}},
    "android_drive": {"input": {"action": "list"}, "params": {}},
    "vector_search": {"input": {"text": "concrete curing methods"}, "params": {"action": "search"}},
        "cache_manager": {
        "input": {
            "action": "get",
            "key": "test",
            "tenant_id": "t1",
            "project_id": "p1",
            "source_class": "official_guidance",
        },
        "params": {},
    },
    "capture":    {"input": {"text": "Screenshot of building plan"}, "params": {"action": "capture"}},
    "agent_swarm": {"input": {"objective": "Analyze construction costs", "agents": []}, "params": {}},
    "workflow":   {"input": {"steps": [{"block": "chat", "action": "status"}]}, "params": {"action": "run"}},
    "notification": {"input": {"channel": "email", "message": "Test alert"}, "params": {"action": "send"}},
    "knowledge":  {"input": {"question": "What is concrete curing?"}, "params": {}},
}

async def main():
    print("="*90)
    print("BLOCK TEST — REAL INPUTS (not 'status' placeholder)")
    print("="*90 + "\n")
    
    real_success = []      # Returns real data
    api_key_needed = []    # Needs API key
    file_needed = []       # Needs real file
    graceful_error = []    # Handles error properly
    broken = []            # Crashes
    
    for name in sorted(BLOCK_REGISTRY.keys()):
        test = TEST_INPUTS.get(name, {"input": {}, "params": {"action": "status"}})
        block = BLOCK_REGISTRY[name]()
        
        try:
            result = await block.execute(test["input"], test["params"])
            status = result.get("status", "unknown")
            
            if status == "success":
                # Check if it returned REAL data or just a placeholder
                result_data = result.get("result", {})
                is_placeholder = (
                    result_data.get("placeholder") == True or
                    result_data.get("note", "").startswith("Using free") or
                    "placeholder" in str(result_data).lower()
                )
                if is_placeholder:
                    graceful_error.append((name, "placeholder response"))
                else:
                    real_success.append((name, str(list(result_data.keys())[:5])))
            elif status == "error":
                err = str(result.get("error", result.get("result", {})))
                if any(x in err.lower() for x in ["api key", "api_key", "key required", "not authenticated"]):
                    api_key_needed.append((name, err[:60]))
                elif any(x in err.lower() for x in ["file_path", "file not found", "no file", "no input files"]):
                    file_needed.append((name, err[:60]))
                else:
                    graceful_error.append((name, err[:60]))
            else:
                graceful_error.append((name, f"status={status}"))
                
        except Exception as e:
            broken.append((name, f"{type(e).__name__}: {str(e)[:60]}"))
    
    # Report
    print(f"✅ REAL SUCCESS ({len(real_success)}):")
    for name, detail in real_success:
        print(f"   {name:25} → {detail}")
    
    print(f"\n🔑 NEEDS API KEY ({len(api_key_needed)}):")
    for name, detail in api_key_needed:
        print(f"   {name:25} → {detail}")
    
    print(f"\n📄 NEEDS REAL FILE ({len(file_needed)}):")
    for name, detail in file_needed:
        print(f"   {name:25} → {detail}")
    
    print(f"\n⚠️  GRACEFUL ERROR ({len(graceful_error)}):")
    for name, detail in graceful_error:
        print(f"   {name:25} → {detail}")
    
    print(f"\n❌ BROKEN / CRASH ({len(broken)}):")
    for name, detail in broken:
        print(f"   {name:25} → {detail}")
    
    print(f"\n{'='*90}")
    print(f"SUMMARY: {len(real_success)} real success | {len(api_key_needed)} need API key | {len(file_needed)} need file | {len(graceful_error)} graceful error | {len(broken)} broken")
    print(f"{'='*90}")
    
    if broken:
        print(f"\n🚨 {len(broken)} blocks are GENUINELY BROKEN and need fixing:")
        for name, _ in broken:
            print(f"   • {name}")

if __name__ == "__main__":
    asyncio.run(main())
