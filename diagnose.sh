#!/usr/bin/env bash
# Health-check the local pipeline plumbing. Run when test_real_files.sh
# surfaces issues to figure out which moving part is missing.
set -u

cd "$(dirname "$0")"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "DIAGNOSTICS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo
echo "1. uploads/ directory state"
if [ -d uploads ]; then
    for dir in uploads/*/; do
        name=$(basename "$dir")
        n=$(find "$dir" -maxdepth 2 -type f 2>/dev/null | wc -l)
        printf "   %-15s %d file(s)\n" "$name" "$n"
    done
else
    echo "   uploads/ missing"
fi

echo
echo "2. Python libraries"
python3 - << 'EOF'
mods = [
    ("fitz",          "PyMuPDF — PDF text extraction"),
    ("ezdxf",         "DXF / drawing_qto"),
    ("ifcopenshell",  "IFC / BIM"),
    ("pint",          "Pint — formula unit validation"),
    ("sympy",         "SymPy — symbolic reasoning"),
    ("docx",          "python-docx (optional, for .docx)"),
    ("CoolProp",      "CoolProp (optional library backend)"),
    ("QuantLib",      "QuantLib (optional library backend)"),
    ("mlflow",        "MLflow (optional tracker)"),
    ("prometheus_client", "Prometheus client (metrics endpoint)"),
    ("asyncpg",       "asyncpg (Postgres backend for historical_benchmark)"),
]
for mod, desc in mods:
    try:
        __import__(mod)
        print(f"   [ok]    {mod:22} {desc}")
    except ImportError as e:
        print(f"   [miss]  {mod:22} {desc}  ({e})")
EOF

echo
echo "3. Block registry — critical blocks reachable"
python3 - << 'EOF'
import os
os.environ.setdefault("ENV", "test")
from app.blocks import BLOCK_REGISTRY
critical = ["chat", "pdf", "ocr", "construction", "drawing_qto",
            "primavera_parser", "bim_extractor", "library_container",
            "validation", "learning_engine"]
for name in critical:
    print(f"   {'[ok]   ' if name in BLOCK_REGISTRY else '[MISS] '} {name}")
EOF

echo
echo "4. Container action surface — count of registered actions"
python3 - << 'EOF'
import os
os.environ.setdefault("ENV", "test")
from app.containers.construction import ConstructionContainer
c = ConstructionContainer()
actions = c.get_actions() if hasattr(c, "get_actions") else {}
print(f"   construction container exposes {len(actions)} action(s)")
EOF

echo
echo "5. File sizes (top 10 largest in uploads/)"
if [ -d uploads ]; then
    find uploads -type f -exec du -h {} + 2>/dev/null | sort -h | tail -10 || true
fi

echo
echo "DONE"
