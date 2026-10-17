#!/usr/bin/env python3
"""Measure L2.2 brief-scope fields from block code. Do not invent.

Reads each ``block_registry/*/block.json``, locates the implementing
source (``app/blocks/{id}.py`` or package, then the registry adapter),
and records only resources / fail-loud checks that appear in that code.

Empty lists mean "looked, could not honestly claim". Those are leftovers
to report, not scopes to fabricate.

Acceptance leftovers after the measured backfill (no fail-loud sentence
in implementing source that this script can honestly pin): see
``--summary``. ``never`` is empty on most blocks on purpose -- a missing
use is not a prohibition.

Usage:
    python scripts/measure_brief_scope.py            # print JSON report
    python scripts/measure_brief_scope.py --apply    # write fields onto manifests
    python scripts/measure_brief_scope.py --summary
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "block_registry"
APP_BLOCKS = ROOT / "app" / "blocks"

# kind -> (scope, evidence-regex). First matching evidence wins a claim.
# Conservative: a hit in implementing source, not in comments-only files.

_READ_PATTERNS: List[Tuple[str, str, str]] = [
    ("caller", "input", r"\binput_data\b|\bparams\b"),
    ("file", "local.read", r"\bopen\(|Path\([^)]*\)\.read_|read_text\(|read_bytes\(|read_json\("),
    ("file", "input_document", r"fitz\.open|PdfReader|pdfplumber|PdfConverter|PyPDF2"),
    ("file", "input_image", r"Image\.open|image_to_string|pytesseract"),
    ("env", "process", r"os\.getenv|os\.environ"),
    ("config", "runtime", r"self\.config|default_config"),
    ("network", "http.outbound", r"\bhttpx\.|requests\.(get|post|put|delete)|aiohttp\.|urllib\.request"),
    ("network", "smtp.outbound", r"\bsmtplib\b|SMTP\("),
    ("database", "sql", r"\bsqlite3\b|\bpsycopg|\bsqlalchemy\b|CREATE TABLE|INSERT INTO|SELECT "),
    ("database", "vector", r"chromadb|vector_store|list_collections|query_collection"),
    ("index", "search", r"hybrid_retriev|similarity_search|embed_query|embed_documents"),
    ("llm", "provider", r"ChatCompletion|openai|moonshot|kimi|llm_config|chat\.completions"),
    ("secrets", "vault", r"SecretsBlock|_load_master_key|Fernet\("),
    ("credential", "env", r"API_KEY|MASTER_KEY|sendgrid_key|ses_key"),
    ("memory", "cache", r"secrets_cache|cache_manager|redis|\.cache\b"),
    ("block", "peer", r"BLOCK_REGISTRY\[|get_block\(|get_block_instance\("),
    ("audit", "log", r"access_log|audit_access|ActionRun"),
    ("queue", "jobs", r"asyncio\.Queue|enqueue|dequeue|job_queue"),
    ("team", "state", r"team_state|TeamBlock"),
    ("dataset", "local", r"knowledge_base|kb\.json|procedures_db"),
]

_WRITE_PATTERNS: List[Tuple[str, str, str]] = [
    ("caller", "output", r"return \{|BlockResult\("),
    ("file", "local.write", r"open\([^)]*['\"]w|write_text\(|write_bytes\(|\.write\("),
    ("file", "temp", r"tempfile\.|NamedTemporaryFile|mkdtemp|mkstemp"),
    ("database", "sql", r"INSERT INTO|UPDATE |DELETE FROM|create_table|executemany\("),
    ("database", "vector", r"add_documents|upsert|index_documents|create_collection"),
    ("network", "http.outbound", r"httpx\.(post|put|delete|patch)|requests\.(post|put|delete)|aiohttp"),
    ("network", "smtp.outbound", r"sendmail\(|sendgrid|SMTP\("),
    ("email", "outbound", r"_send_email|_send_smtp|_send_sendgrid|_send_ses|send_template"),
    ("notification", "outbound", r"send_notification|notify\(|NotificationBlock"),
    ("audit", "log", r"access_log\.append|audit_store|record_audit"),
    ("memory", "cache", r"cache\[|secrets_cache\[|set_cache|memory\.set"),
    ("queue", "jobs", r"enqueue\(|put_nowait\("),
    ("subprocess", "local", r"subprocess\.|Popen\(|asyncio\.create_subprocess"),
]

# Explicit prohibitions only. Absence of a use is NOT a never.
_NEVER_PATTERNS: List[Tuple[str, str, str]] = [
    ("network", "guest_code_outbound", r"network_allowed.*False"),
    ("file", "escape_root", r"would escape|confined to|cannot read, write, or\s+list anything outside"),
    ("secrets", "derived_constant_key", r"derived-from-constant"),
    ("subprocess", "eval_exec", r"blocked_builtins"),
    (
        "caller",
        "trust_scope",
        r"RESERVED_CONTEXT_KEYS|trust scope is server-controlled",
    ),
]

# Registry ids whose implementing source is not app/blocks/{id}.py.
_SOURCE_OVERRIDES: Dict[str, List[Path]] = {
    "action_contract": [APP_BLOCKS / "core" / "action_contract"],
    "construction": [ROOT / "app" / "containers" / "construction"],
    "finance_ops": [ROOT / "app" / "containers" / "finance_ops.py"],
    "insurance": [ROOT / "app" / "containers" / "insurance.py"],
    "document_engine": [
        APP_BLOCKS / "document_engine_block.py",
        APP_BLOCKS / "document_engine.py",
        APP_BLOCKS / "document_engine",
    ],
}

_ACCEPT_PATTERNS: List[Tuple[str, str, str, str]] = [
    # id, sentence, status, evidence
    (
        "missing_required_input",
        "refuses or errors when a required input is absent",
        "refused",
        r"is required|not provided|No PDF|No code provided|No image provided|"
        r"Query is required|A URL is required|missing required|"
        r"Text input required|Text required|file_path required",
    ),
    (
        "unknown_action",
        "errors on an unknown or missing action",
        "failed",
        r"Unknown action|unknown action|Unknown operation",
    ),
    (
        "path_escape_rejected",
        "rejects paths that escape the configured root",
        "refused",
        r"would escape|escape the root|path.*reject",
    ),
    (
        "missing_credential",
        "fails loud when a required credential or key is absent",
        "failed",
        r"API key not configured|is not set\.|MASTER_KEY|not configured",
    ),
    (
        "not_implemented",
        "returns not_implemented rather than inventing a result",
        "refused",
        r"not_implemented|NotImplementedError",
    ),
]


def _iter_py(paths: Iterable[Path]) -> List[Path]:
    files: List[Path] = []
    for path in paths:
        if path.is_file() and path.suffix == ".py":
            files.append(path)
        elif path.is_dir():
            files.extend(sorted(p for p in path.rglob("*.py") if "__pycache__" not in p.parts))
    return files


def _source_paths(block_id: str) -> List[Path]:
    """Implementing source, preferring app/blocks over the thin adapter."""
    if block_id in _SOURCE_OVERRIDES:
        return _iter_py(_SOURCE_OVERRIDES[block_id])

    candidates: List[Path] = []
    module = APP_BLOCKS / f"{block_id}.py"
    package = APP_BLOCKS / block_id
    if module.is_file():
        candidates.append(module)
    if package.is_dir():
        candidates.append(package)
    container = ROOT / "app" / "containers" / f"{block_id}.py"
    if container.is_file():
        candidates.append(container)
    adapter = REGISTRY / block_id / "block.py"
    if not candidates and adapter.is_file():
        candidates.append(adapter)
    return _iter_py(candidates)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _matched(patterns: List[Tuple[str, str, str]], text: str) -> List[Dict[str, str]]:
    found: List[Dict[str, str]] = []
    seen: Set[Tuple[str, str]] = set()
    for kind, scope, pattern in patterns:
        if (kind, scope) in seen:
            continue
        if re.search(pattern, text):
            seen.add((kind, scope))
            found.append({"kind": kind, "scope": scope})
    return found


def _acceptance(text: str) -> List[Dict[str, str]]:
    found: List[Dict[str, str]] = []
    seen: Set[str] = set()
    for ident, check, status, pattern in _ACCEPT_PATTERNS:
        if ident in seen:
            continue
        if re.search(pattern, text, re.I):
            seen.add(ident)
            found.append({"id": ident, "check": check, "status": status})
    return found


def _never(text: str) -> List[Dict[str, str]]:
    """Only explicit bans in implementing source, not adapters."""
    return _matched(_NEVER_PATTERNS, text)


def measure_block(block_id: str) -> Dict[str, Any]:
    paths = _source_paths(block_id)
    text = "\n".join(_read(p) for p in paths)
    leftovers: List[str] = []
    if not text.strip():
        leftovers.append("no implementing source found")
        return {
            "id": block_id,
            "source_files": [],
            "reads": [],
            "writes": [],
            "never": [],
            "acceptance": [],
            "leftovers": leftovers,
        }

    reads = _matched(_READ_PATTERNS, text)
    writes = _matched(_WRITE_PATTERNS, text)
    never = _never(text)
    acceptance = _acceptance(text)

    # Every UniversalBlock/container handler reads the request and returns
    # a payload. Measured from the process/run signature, not hoped.
    if re.search(r"def process\(|def run\(|def execute\(|def execute_action\(", text):
        if not any(e["kind"] == "caller" and e["scope"] == "input" for e in reads):
            reads.insert(0, {"kind": "caller", "scope": "input"})
        if not any(e["kind"] == "caller" and e["scope"] == "output" for e in writes):
            writes.insert(0, {"kind": "caller", "scope": "output"})

    if not reads:
        leftovers.append("reads unmeasured")
    if not writes:
        leftovers.append("writes unmeasured")
    # never and acceptance may honestly be empty.

    return {
        "id": block_id,
        "source_files": [str(p.relative_to(ROOT)) for p in paths],
        "reads": reads,
        "writes": writes,
        "never": never,
        "acceptance": acceptance,
        "leftovers": leftovers,
    }


def registry_ids() -> List[str]:
    return sorted(
        p.name
        for p in REGISTRY.iterdir()
        if p.is_dir() and not p.name.startswith("__") and (p / "block.json").is_file()
    )


def apply_measurement(measurement: Dict[str, Any]) -> None:
    path = REGISTRY / measurement["id"] / "block.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    # Preserve existing key order; append the four fields.
    manifest["reads"] = measurement["reads"]
    manifest["writes"] = measurement["writes"]
    manifest["never"] = measurement["never"]
    manifest["acceptance"] = measurement["acceptance"]
    path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    # Keep finance_ops kit twins in sync when they are byte-identical copies
    # of the store id (same id field). Other kit copies are left alone.
    for twin in ROOT.glob(
        f"block_store/kits/*/bundle/block_registry/{measurement['id']}/block.json"
    ):
        twin_manifest = json.loads(twin.read_text(encoding="utf-8"))
        if twin_manifest.get("id") != measurement["id"]:
            continue
        twin_manifest["reads"] = measurement["reads"]
        twin_manifest["writes"] = measurement["writes"]
        twin_manifest["never"] = measurement["never"]
        twin_manifest["acceptance"] = measurement["acceptance"]
        twin.write_text(
            json.dumps(twin_manifest, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()

    rows = [measure_block(block_id) for block_id in registry_ids()]
    leftovers = [row for row in rows if row["leftovers"]]
    empty_never = sum(1 for row in rows if not row["never"])
    empty_accept = sum(1 for row in rows if not row["acceptance"])

    if args.summary:
        print("blocks:", len(rows))
        print("with source:", sum(1 for row in rows if row["source_files"]))
        print("reads empty:", sum(1 for row in rows if not row["reads"]))
        print("writes empty:", sum(1 for row in rows if not row["writes"]))
        print("never empty (ok if no ban):", empty_never)
        print("acceptance empty:", empty_accept)
        print("leftover blocks:", len(leftovers))
        for row in leftovers:
            print(" -", row["id"], ",", ". ".join(row["leftovers"]))
        return 0

    if args.apply:
        for row in rows:
            apply_measurement(row)
        print("applied brief-scope fields to", len(rows), "registry manifests")
        return 0

    json.dump(
        {
            "blocks": rows,
            "counts": {
                "total": len(rows),
                "leftovers": len(leftovers),
                "never_empty": empty_never,
                "acceptance_empty": empty_accept,
            },
        },
        sys.stdout,
        indent=2,
    )
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
