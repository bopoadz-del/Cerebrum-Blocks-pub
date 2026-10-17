import os
from pathlib import Path

ROOT = Path(__file__).parent.parent
BLOCKS_DIR = ROOT / "app" / "blocks"
KITS_DIR = ROOT / "block_store" / "kits"

# 1. List all .py files in app/blocks/
all_blocks = sorted([f.name for f in BLOCKS_DIR.glob("*.py") if f.name != "__init__.py"])
print(f"Total .py files in app/blocks/: {len(all_blocks)}")

# 2. Define categories (based on naming convention)
generic = [f for f in all_blocks if not f.endswith("_v2.py") and not f.startswith("container_") and f != "historical_benchmark.py"]
domain_v2 = [f for f in all_blocks if f.endswith("_v2.py")]
legacy = [f for f in all_blocks if f.startswith("container") or f == "historical_benchmark.py"]

print(f"\n[OK] Generic platform blocks: {len(generic)}")
print(f"[OK] Domain v2 blocks: {len(domain_v2)}")
print(f"[WARN] Legacy/unreferenced blocks: {len(legacy)}")

# 3. Cross-check with block_store kits
kits = [d.name for d in KITS_DIR.iterdir() if d.is_dir() and (d / "manifest.json").exists()]
print(f"\n[STORE] Kits in block_store: {len(kits)}")
for kit in kits:
    bundle_blocks = KITS_DIR / kit / "bundle" / "app" / "blocks"
    if bundle_blocks.exists():
        v2_files = [f.name for f in bundle_blocks.glob("*_v2.py")]
        print(f"  - {kit}: {v2_files}")

# 4. Recommendations
if legacy:
    print("\n[RM] RECOMMENDATION: Delete these legacy files:")
    for f in legacy:
        print(f"   rm {BLOCKS_DIR / f}")
