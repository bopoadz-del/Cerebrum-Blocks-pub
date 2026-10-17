"""Fan-out: which consuming products use a given store block."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ConsumerHit:
    product: str
    repo: str
    kits: tuple[str, ...]
    blocks: tuple[str, ...]
    needs_fix_on_next_build: bool
    notes: str = ""


@dataclass(frozen=True)
class FanoutReport:
    block_name: str
    consumers: tuple[ConsumerHit, ...]
    unknown_consumers_note: str

    @property
    def flagged_products(self) -> tuple[str, ...]:
        return tuple(c.product for c in self.consumers if c.needs_fix_on_next_build)


def _parse_simple_yaml_consumers(text: str) -> list[dict[str, Any]]:
    """Minimal YAML subset parser for consumers.yaml (no PyYAML required)."""
    consumers: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    list_key: str | None = None

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if line.startswith("consumers:"):
            continue
        if line.startswith("  - "):
            if current:
                consumers.append(current)
            rest = line[4:].strip()
            current = {}
            list_key = None
            if ":" in rest:
                k, v = rest.split(":", 1)
                current[k.strip()] = _scalar(v.strip())
            continue
        if current is None:
            continue
        if line.startswith("    ") and ":" in line and not line.strip().startswith("-"):
            key, val = line.strip().split(":", 1)
            key = key.strip()
            val = val.strip()
            if val == "" or val == "[]":
                current[key] = [] if val == "[]" else []
                list_key = key
            else:
                current[key] = _scalar(val)
                list_key = None
            continue
        if line.startswith("      - ") and list_key:
            current.setdefault(list_key, [])
            assert isinstance(current[list_key], list)
            current[list_key].append(_scalar(line.strip()[2:].strip()))
    if current:
        consumers.append(current)
    return consumers


def _scalar(value: str) -> Any:
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    return value


def load_consumers(store_root: Path) -> list[dict[str, Any]]:
    path = store_root / "consumers.yaml"
    if not path.is_file():
        return []
    return _parse_simple_yaml_consumers(path.read_text(encoding="utf-8"))


def fanout_for_block(store_root: Path, block_name: str) -> FanoutReport:
    hits: list[ConsumerHit] = []
    for entry in load_consumers(store_root):
        blocks = tuple(entry.get("blocks") or [])
        kits = tuple(entry.get("kits") or [])
        # Match by explicit block list, kit id containing the block name, or "*".
        uses = block_name in blocks or any(block_name == (k or "") for k in kits)
        wild = "*" in blocks
        if uses or wild:
            hits.append(
                ConsumerHit(
                    product=str(entry.get("product") or entry.get("name") or "unknown"),
                    repo=str(entry.get("repo") or ""),
                    kits=kits,
                    blocks=blocks,
                    needs_fix_on_next_build=True,
                    notes=str(entry.get("notes") or ""),
                )
            )
    note = (
        "Consumers listed in store consumers.yaml; "
        "flag means pull store pin on next product build."
        if hits
        else "No consumers.yaml entries matched — fan-out unknown; human review."
    )
    return FanoutReport(
        block_name=block_name,
        consumers=tuple(hits),
        unknown_consumers_note=note,
    )


def write_fanout_report(proposal_dir: Path, report: FanoutReport) -> Path:
    proposal_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Fan-out for block `{report.block_name}`",
        "",
        report.unknown_consumers_note,
        "",
        "| Product | Repo | Needs fix on next build | Kits |",
        "|---------|------|-------------------------|------|",
    ]
    for c in report.consumers:
        lines.append(
            f"| {c.product} | {c.repo} | {'yes' if c.needs_fix_on_next_build else 'no'} | "
            f"{', '.join(c.kits) or '—'} |"
        )
    if not report.consumers:
        lines.append("| _(none matched)_ | | | |")
    lines.append("")
    lines.append("## Flagged products")
    if report.flagged_products:
        for p in report.flagged_products:
            lines.append(f"- {p}")
    else:
        lines.append("- _(none)_")
    out = proposal_dir / "fanout.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
