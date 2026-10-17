#!/usr/bin/env python3
from pathlib import Path
import json

root = Path(__file__).parent.parent / "block_registry"
for block_dir in root.iterdir():
    if not block_dir.is_dir() or block_dir.name == "__pycache__":
        continue
    manifest_path = block_dir / "block.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not manifest.get("author"):
            manifest["author"] = "Cerebrum Team"
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    dockerfile = block_dir / "Dockerfile"
    if dockerfile.exists():
        text = dockerfile.read_text(encoding="utf-8")
        updated = text.replace(
            'ENTRYPOINT ["python", "run.py"]',
            'ENTRYPOINT ["python", "/app/run.py"]',
        )
        if updated != text:
            dockerfile.write_text(updated, encoding="utf-8")

print("metadata + dockerfiles patched")
