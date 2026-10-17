#!/usr/bin/env python3
"""Inject ui_schema into app/blocks modules that are missing it."""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import importlib.util

_builder_path = ROOT / "app" / "core" / "ui_schema_builder.py"
_spec = importlib.util.spec_from_file_location("ui_schema_builder", _builder_path)
_builder = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_builder)

action_ui_schema = _builder.action_ui_schema
file_ui_schema = _builder.file_ui_schema
payload_ui_schema = _builder.payload_ui_schema
text_ui_schema = _builder.text_ui_schema

BLOCKS_DIR = ROOT / "app" / "blocks"
SKIP = {"__init__", "container", "container_ai_core", "container_construction", "container_infrastructure", "container_platform", "container_security", "container_store", "container_team", "container_utility"}


def _schema() -> dict:
    return {
        "adaptive_router": action_ui_schema(
            ["select_provider", "record_result", "get_recommendation", "forecast_issues", "get_scores", "reset_scores", "ab_test", "explain_choice"],
            placeholder="Task, quality tier, budget, provider constraints...",
        ),
        "analytics": action_ui_schema(
            ["track_event", "leaderboard", "usage_report", "predict_failure", "cost_analysis", "get_metrics", "compare_providers"],
            config_params={"window_size": 100, "prediction_threshold": 0.3},
        ),
        "audit": action_ui_schema(
            ["log", "query", "export", "verify_chain", "get_stats", "tamper_check"],
            output_fields=[{"name": "events", "type": "json", "label": "Audit Events"}],
        ),
        "auth": action_ui_schema(
            ["validate", "check_rate_limit", "check_permission", "create_key", "revoke_key", "rotate_key", "get_usage", "list_keys"],
            output_fields=[{"name": "authorized", "type": "boolean", "label": "Authorized"}],
        ),
        "billing": action_ui_schema(
            ["record_usage", "check_quota", "create_customer", "create_subscription", "get_invoice", "upgrade", "webhook"],
        ),
        "bim": action_ui_schema(
            ["index_folder", "parse_ifc", "extract_dwg_metadata", "process_pdf", "get_elements", "spatial_query", "compare_versions"],
            input_type="file",
            placeholder="IFC/DWG/PDF path or folder payload",
        ),
        "config": action_ui_schema(["get", "get_all", "set"], placeholder="Config key/value payload"),
        "dashboard": action_ui_schema(
            ["render", "add_widget", "remove_widget", "update_widget", "get_metrics", "list_widgets", "save_layout", "get_layout", "subscribe_stream", "get_snapshot"],
        ),
        "database": action_ui_schema(
            ["query", "insert", "update", "delete", "create_table", "list_tables"],
            output_fields=[{"name": "rows", "type": "json", "label": "Rows"}],
        ),
        "discovery": action_ui_schema(
            ["recommend_for_project", "find_alternative", "search_blocks", "trending", "get_compatible", "index_block", "get_categories", "smart_stack"],
            placeholder="Project goal, block query, or indexing payload",
        ),
        "documentation": action_ui_schema(
            ["generate_docs", "extract_signature", "create_playground", "search_docs", "add_example", "get_examples", "render_markdown", "validate_docs"],
        ),
        "email": action_ui_schema(["send", "send_template", "validate_address"], placeholder="Recipient, subject, body, template data"),
        "error_tracking": action_ui_schema(
            ["capture_exception", "capture_message", "get_issue", "resolve_issue", "performance_trace", "end_trace", "get_issues", "get_stats", "add_breadcrumb"],
        ),
        "failover": payload_ui_schema(
            input_fields=[
                {"name": "block", "type": "string", "label": "Primary block"},
                {"name": "payload", "type": "json", "label": "Execution payload"},
            ],
            output_fields=[{"name": "result", "type": "json", "label": "Failover result"}],
        ),
        "health_check": action_ui_schema(
            ["ping", "deep_check", "check_dependency", "register_probe", "unregister_probe", "get_status", "get_history", "simulate_failure"],
            output_fields=[{"name": "status", "type": "text", "label": "Health status"}],
        ),
        "memory": action_ui_schema(
            ["get", "set", "delete", "exists", "flush", "stats", "keys"],
            placeholder='Cache key/value payload, e.g. {"key": "session", "value": {...}}',
            config_params={"max_size": 10000, "default_ttl": 3600, "cleanup_interval": 300},
        ),
        "migration": action_ui_schema(
            ["migrate", "rollback", "status", "create_migration", "seed_data", "list_pending", "verify", "force_version"],
        ),
        "monitoring": action_ui_schema(
            ["record_call", "leaderboard", "provider_status", "recommend", "health_report", "predictive_failover"],
            config_params={"track_providers": ["deepseek", "anthropic"], "window_size": 100, "prediction_threshold": 0.3},
        ),
        "payment_split": action_ui_schema(
            ["calculate_split", "process_sale", "process_payout", "register_creator", "update_creator", "revenue_report", "creator_dashboard", "transfer_ownership", "get_transaction", "list_transactions", "hold_funds", "release_hold"],
        ),
        "queue": action_ui_schema(
            ["enqueue", "dequeue", "status", "list"],
            placeholder="Job type, payload, queue name",
            config_params={"backend": "memory", "redis_url": None, "max_workers": 4},
        ),
        "rate_limiter": action_ui_schema(
            ["check_limit", "record_hit", "set_custom_limit", "get_usage_stats", "reset_limit", "get_limit_info"],
        ),
        "review": action_ui_schema(["approve", "reject", "hide"], placeholder="Review item id and metadata"),
        "sandbox": action_ui_schema(
            ["execute", "validate_code", "create_policy", "wrap_block", "get_stats", "check_safety"],
            input_type="json",
            placeholder='{"code": "print(1+1)", "language": "python"}',
            config_params={
                "default_level": "strict",
                "max_memory_mb": 512,
                "max_cpu_time": 5,
                "network_allowed": False,
                "filesystem_readonly": True,
                "auto_kill": True,
            },
        ),
        "secrets": action_ui_schema(
            ["set", "get", "delete", "list", "encrypt", "decrypt", "hash"],
            output_fields=[{"name": "secret", "type": "json", "label": "Secret value"}],
        ),
        "storage": action_ui_schema(["store", "retrieve", "delete", "exists", "list"]),
        "team": action_ui_schema(
            ["create_team", "delete_team", "invite_member", "accept_invitation", "remove_member", "set_role", "get_team", "list_teams", "get_members", "get_team_context", "switch_team", "check_permission"],
        ),
        "validation": action_ui_schema(["validate_pipeline"], placeholder="Pipeline definition to validate"),
        "vector": action_ui_schema(["add", "search", "delete", "get", "count"], placeholder="Vector id, embedding, or query"),
        "version": action_ui_schema(
            ["publish_version", "check_compatibility", "rollback", "deprecate", "dependency_tree", "get_version", "list_versions", "compare_versions", "get_changelog", "suggest_update", "validate_version", "yank_version"],
        ),
        "webhook": action_ui_schema(
            ["register", "send", "trigger", "list"],
            placeholder="Webhook URL, events, payload",
            config_params={"timeout": 30, "retries": 3, "verify_ssl": True},
        ),
    }


def _python_literal(value) -> str:
    return repr(value)


def _format_assignment(schema: dict) -> str:
    lines = ["    ui_schema = {"]
    for key, val in schema.items():
        lines.append(f"        {_python_literal(key)}: {_python_literal(val)},")
    lines.append("    }")
    return "\n".join(lines)


def _insert_after_default_config(content: str, assignment: str) -> str | None:
    if "ui_schema" in content:
        return None
    match = re.search(r"default_config\s*=\s*\{", content)
    if not match:
        return None
    start = match.end() - 1
    depth = 0
    for idx in range(start, len(content)):
        char = content[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return content[: idx + 1] + "\n\n" + assignment + content[idx + 1 :]
    return None


def main() -> int:
    schemas = _schema()
    updated = 0
    for name, schema in schemas.items():
        path = BLOCKS_DIR / f"{name}.py"
        if not path.exists():
            print(f"[SKIP] missing module {name}.py")
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        if "ui_schema" in content:
            continue
        assignment = _format_assignment(schema)
        new_content = _insert_after_default_config(content, assignment)
        if not new_content:
            print(f"[FAIL] could not inject into {name}.py")
            continue
        path.write_text(new_content, encoding="utf-8")
        updated += 1
        print(f"[OK] injected ui_schema into {name}.py")
    print(f"Updated {updated} block modules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
