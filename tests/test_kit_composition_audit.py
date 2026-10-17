"""The composition audit must actually refuse things.

A gate is only a gate if it blocks. These tests assert each finding fires on
a kit built to trigger it, that a well-formed kit is accepted, and that the
real repository passes -- so the audit cannot rot into a no-op that reports
success because it stopped looking.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "audit_kit_composition.py"


def _load():
    spec = importlib.util.spec_from_file_location("audit_kit_composition", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


audit = _load()


def _kit(root: Path, name: str, manifest, *, raw: str | None = None) -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    text = raw if raw is not None else json.dumps(manifest)
    (d / "manifest.json").write_text(text, encoding="utf-8")
    return d


def _base(**over):
    body = {
        "id": "demo",
        "name": "Demo",
        "version": "1.0.0",
        "description": "d",
        "status": "available",
        "blocks": ["alpha", "beta"],
    }
    body.update(over)
    return body


def _codes(kit_dir: Path, kit: str, known=("alpha", "beta")):
    return [c for c, _ in audit.audit_kit(kit, str(kit_dir), set(known))]


# --------------------------------------------------------------------------
# Silence is not permission.
# --------------------------------------------------------------------------


def test_multi_block_kit_without_composition_is_a_finding(tmp_path):
    _kit(tmp_path, "demo", _base())
    assert "no_composition" in _codes(tmp_path, "demo")


def test_single_block_kit_needs_no_composition(tmp_path):
    _kit(tmp_path, "demo", _base(blocks=["alpha"]))
    assert "no_composition" not in _codes(tmp_path, "demo")


def test_flow_satisfies_the_composition_requirement(tmp_path):
    _kit(tmp_path, "demo", _base(flow=[["alpha"], ["beta"]]))
    assert _codes(tmp_path, "demo") == []


def test_waves_is_accepted_as_a_legacy_spelling(tmp_path):
    """universal_kernel predates this audit; migrating it would create two
    keys meaning the same thing."""
    _kit(tmp_path, "demo", _base(waves={"wave1": ["alpha"], "wave2": ["beta"]}))
    assert _codes(tmp_path, "demo") == []


def test_a_flat_flow_list_is_accepted(tmp_path):
    _kit(tmp_path, "demo", _base(flow=["alpha", "beta"]))
    assert _codes(tmp_path, "demo") == []


def test_an_empty_flow_does_not_pass_as_a_declaration(tmp_path):
    """Declaring `flow: []` for a two-block kit still leaves both unordered."""
    _kit(tmp_path, "demo", _base(flow=[]))
    assert "composition_incomplete" in _codes(tmp_path, "demo")


# --------------------------------------------------------------------------
# Agreement between the composition and the block list.
# --------------------------------------------------------------------------


def test_flow_omitting_a_block_is_a_finding(tmp_path):
    _kit(tmp_path, "demo", _base(flow=[["alpha"]]))
    codes = _codes(tmp_path, "demo")
    assert "composition_incomplete" in codes


def test_flow_ordering_a_non_member_is_a_finding(tmp_path):
    _kit(tmp_path, "demo", _base(flow=[["alpha", "beta", "ghost"]]))
    assert "composition_unknown_block" in _codes(tmp_path, "demo")


# --------------------------------------------------------------------------
# Manifest integrity.
# --------------------------------------------------------------------------


def test_unresolved_block_is_a_finding(tmp_path):
    _kit(tmp_path, "demo", _base(blocks=["alpha", "nope"], flow=["alpha", "nope"]))
    assert "unresolved_block" in _codes(tmp_path, "demo")


def test_a_kit_may_vendor_its_own_blocks(tmp_path):
    """universal_kernel resolves via wave1/... rather than block_registry."""
    d = _kit(tmp_path, "demo", _base(blocks=["local_one"], flow=["local_one"]))
    (d / "wave1" / "local_one").mkdir(parents=True)
    assert _codes(tmp_path, "demo", known=()) == []


def test_a_kit_may_vendor_blocks_in_the_bundle_app_blocks_layout(tmp_path):
    """Published kits put modules at bundle/app/blocks/<name>.py."""
    d = _kit(tmp_path, "demo", _base(blocks=["local_one"], flow=["local_one"]))
    blocks = d / "bundle" / "app" / "blocks"
    blocks.mkdir(parents=True)
    (blocks / "local_one.py").write_text("# vendored\n", encoding="utf-8")
    assert _codes(tmp_path, "demo", known=()) == []


def test_duplicate_blocks_are_a_finding(tmp_path):
    _kit(tmp_path, "demo", _base(blocks=["alpha", "alpha"], flow=["alpha"]))
    assert "duplicate_blocks" in _codes(tmp_path, "demo")


def test_id_mismatch_is_a_finding(tmp_path):
    _kit(tmp_path, "demo", _base(id="something_else", flow=["alpha", "beta"]))
    assert "id_mismatch" in _codes(tmp_path, "demo")


def test_missing_required_key_is_a_finding(tmp_path):
    body = _base(flow=["alpha", "beta"])
    del body["version"]
    _kit(tmp_path, "demo", body)
    assert "missing_key" in _codes(tmp_path, "demo")


def test_unparseable_manifest_is_a_finding_not_a_crash(tmp_path):
    _kit(tmp_path, "demo", None, raw="{not json")
    assert _codes(tmp_path, "demo") == ["manifest_unparseable"]


def test_missing_manifest_is_a_finding(tmp_path):
    (tmp_path / "demo").mkdir()
    assert _codes(tmp_path, "demo") == ["no_manifest"]


def test_blocks_must_be_a_list(tmp_path):
    _kit(tmp_path, "demo", _base(blocks="alpha"))
    assert "blocks_not_a_list" in _codes(tmp_path, "demo")


# --------------------------------------------------------------------------
# The audit as a CI gate.
# --------------------------------------------------------------------------


def test_registration_file_parses_known_gaps(tmp_path, monkeypatch):
    (tmp_path / "KNOWN_KIT_GAPS.md").write_text(
        "# heading\n\ntext\n\n- demo :: no_composition  because\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    assert audit.load_known() == {"demo :: no_composition"}


def _mini_repo(tmp_path: Path) -> Path:
    """A repo where alpha/beta resolve, so only the composition gap fires."""
    kits = tmp_path / "block_store" / "kits"
    _kit(kits, "demo", _base())
    for b in ("alpha", "beta"):
        (tmp_path / "block_registry" / b).mkdir(parents=True, exist_ok=True)
    return kits


def test_main_exits_nonzero_on_an_unregistered_finding(tmp_path, monkeypatch):
    _mini_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert audit.main([]) == 1


def test_main_exits_zero_once_the_finding_is_registered(tmp_path, monkeypatch):
    _mini_repo(tmp_path)
    (tmp_path / "KNOWN_KIT_GAPS.md").write_text(
        "- demo :: no_composition  registered\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    assert audit.main([]) == 0


def test_registration_does_not_suppress_a_different_finding(tmp_path, monkeypatch):
    """Registering one code must not blanket-silence the kit."""
    kits = _mini_repo(tmp_path)
    _kit(kits, "demo", _base(blocks=["alpha", "ghost"]))
    (tmp_path / "KNOWN_KIT_GAPS.md").write_text(
        "- demo :: no_composition  registered\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    assert audit.main([]) == 1


def test_the_template_kit_is_skipped_by_name_not_by_parse_failure(tmp_path, monkeypatch):
    """_template carries {{placeholders}} and cannot be JSON. Skipping it by
    name means a real kit with a broken manifest is still caught."""
    kits = tmp_path / "block_store" / "kits"
    _kit(kits, "_template", None, raw='{"id": "{{domain}}", "tags": {{tags_json}}}')
    _kit(kits, "real", None, raw="{also broken")
    monkeypatch.chdir(tmp_path)
    assert audit.main([]) == 1


# --------------------------------------------------------------------------
# Regression lock on the real repository.
# --------------------------------------------------------------------------


def test_this_repository_passes_the_audit(monkeypatch):
    monkeypatch.chdir(REPO)
    assert audit.main([]) == 0, "run: python scripts/audit_kit_composition.py"


def test_universal_kernel_declares_a_complete_composition(monkeypatch):
    """The worked example. If this regresses, the audit lost its only kit
    that demonstrates what a complete declaration looks like."""
    monkeypatch.chdir(REPO)
    known = audit._dirs(audit.REGISTRY_DIR) | audit._modules(audit.MODULES_DIR)
    assert audit.audit_kit("universal_kernel", audit.KITS_DIR, known) == []


# --------------------------------------------------------------------------
# Provenance: an encoded figure must say where it came from.
# --------------------------------------------------------------------------


def _data_kit(root: Path, name: str, files: dict, declared=None):
    """A kit declaring data files, written at the kit root (unpublished)."""
    body = _base(id=name, blocks=["alpha"], data=list(declared if declared is not None else files))
    d = _kit(root, name, body)
    for rel, content in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(content), encoding="utf-8")
    return d


def _pcodes(root: Path, name: str):
    return [c for c, _ in audit._provenance_findings(name, str(root), json.loads(
        (root / name / "manifest.json").read_text(encoding="utf-8")))]


def test_a_data_file_with_no_provenance_is_a_finding(tmp_path):
    _data_kit(tmp_path, "demo", {"rates.json": {"rates": {"a": 0.5}}})
    assert "data_provenance_missing" in _pcodes(tmp_path, "demo")


def test_a_top_level_provenance_record_satisfies_the_check(tmp_path):
    _data_kit(tmp_path, "demo", {"rates.json": {
        "provenance": {"kind": "regulator", "reference": "HKIA GN16 s3.2"},
        "rates": {"a": 0.5},
    }})
    assert _pcodes(tmp_path, "demo") == []


def test_per_item_citation_satisfies_the_check(tmp_path):
    """gn16_ruleset.json records provenance per rule, not per file."""
    _data_kit(tmp_path, "demo", {"rules.json": {
        "rules": [{"rule_id": "r1", "citation": "GN16 s1.2"},
                  {"rule_id": "r2", "citation": "GN16 s3.2"}],
    }})
    assert _pcodes(tmp_path, "demo") == []


def test_one_uncited_item_fails_the_whole_document(tmp_path):
    _data_kit(tmp_path, "demo", {"rules.json": {
        "rules": [{"rule_id": "r1", "citation": "GN16 s1.2"}, {"rule_id": "r2"}],
    }})
    assert "data_provenance_missing" in _pcodes(tmp_path, "demo")


def test_a_cited_collection_cannot_cover_for_an_uncited_one(tmp_path):
    """Regression: an earlier rule passed a file if ANY collection was fully
    cited, so hkia_gn16_corpus.json passed on its 8/8 section_summaries while
    its figures went uncited. Adding one well-cited list must not launder the
    rest of the document."""
    _data_kit(tmp_path, "demo", {"mixed.json": {
        "summaries": [{"id": "s1", "citation": "GN16 s1"}],
        "rates": [{"level": "standard", "rate": 0.75}],
    }})
    assert "data_provenance_missing" in _pcodes(tmp_path, "demo")


def test_a_sources_collection_need_not_cite_itself(tmp_path):
    """Requiring each entry of a 'sources' list to cite a source is circular."""
    _data_kit(tmp_path, "demo", {"corpus.json": {
        "sources": [{"title": "GN16", "url": "https://example.invalid"}],
        "sections": [{"id": "1", "citation": "GN16 s1"}],
    }})
    assert _pcodes(tmp_path, "demo") == []


def test_unverified_figures_must_be_parked(tmp_path):
    """The intake rule enforced rather than remembered."""
    _data_kit(tmp_path, "demo", {"rates.json": {
        "provenance": {"kind": "contributor_unverified", "reference": "sheet from D."},
        "rates": {"a": 0.5},
    }})
    assert "data_unverified_not_parked" in _pcodes(tmp_path, "demo")


def test_parked_unverified_figures_are_accepted(tmp_path):
    _data_kit(tmp_path, "demo", {"rates.json": {
        "provenance": {"kind": "contributor_unverified", "parked": True},
        "rates": {"a": 0.5},
    }})
    assert _pcodes(tmp_path, "demo") == []


def test_an_unknown_source_kind_is_a_finding(tmp_path):
    _data_kit(tmp_path, "demo", {"rates.json": {
        "provenance": {"kind": "vibes", "reference": "x"}, "rates": {"a": 1},
    }})
    assert "data_provenance_kind_unknown" in _pcodes(tmp_path, "demo")


def test_a_cited_kind_without_a_reference_is_a_finding(tmp_path):
    _data_kit(tmp_path, "demo", {"rates.json": {
        "provenance": {"kind": "regulator"}, "rates": {"a": 1},
    }})
    assert "data_provenance_unreferenced" in _pcodes(tmp_path, "demo")


def test_a_declared_data_file_that_is_absent_is_a_finding(tmp_path):
    _data_kit(tmp_path, "demo", {}, declared=["nope.json"])
    assert "data_file_missing" in _pcodes(tmp_path, "demo")


def test_a_declared_directory_is_satisfied_by_the_directory(tmp_path):
    d = _data_kit(tmp_path, "demo", {}, declared=["schemas/"])
    (d / "schemas").mkdir()
    assert _pcodes(tmp_path, "demo") == []


def test_the_gn16_ruleset_still_passes_on_its_own_citations(monkeypatch):
    """The worked example for provenance, as universal_kernel is for flow."""
    monkeypatch.chdir(REPO)
    data = json.loads(Path(
        "block_store/kits/insurance/bundle/app/data/gn16_ruleset.json"
    ).read_text(encoding="utf-8"))
    assert audit._every_item_cited(data)
    assert all(r.get("citation") for r in data["rules"])


def test_declaring_blocks_independent_is_accepted(tmp_path):
    """Not every kit is a pipeline. The 6-block domain kits ship a bundle
    whose container resolves a single block; demanding a flow of them would
    invite a fabricated one."""
    _kit(tmp_path, "demo", _base(flow="independent"))
    assert _codes(tmp_path, "demo") == []


def test_independent_is_case_insensitive(tmp_path):
    _kit(tmp_path, "demo", _base(waves="Independent"))
    assert _codes(tmp_path, "demo") == []


def test_independent_does_not_excuse_an_unresolved_block(tmp_path):
    """Declaring no ordering says nothing about whether the blocks exist."""
    _kit(tmp_path, "demo", _base(blocks=["alpha", "ghost"], flow="independent"))
    assert "unresolved_block" in _codes(tmp_path, "demo")


def test_some_other_string_is_not_a_declaration(tmp_path):
    """Only the declared value counts; a free-text note is still silence."""
    _kit(tmp_path, "demo", _base(flow="see the README"))
    assert "composition_incomplete" in _codes(tmp_path, "demo")


# --------------------------------------------------------------------------
# The generator must produce kits this audit accepts.
# --------------------------------------------------------------------------


def test_a_freshly_generated_kit_passes_the_audit(tmp_path, monkeypatch):
    """The loop that matters: 18 kits lack a composition declaration because
    the generator never emitted one. If this regresses, kit number 21 is a
    new registration rather than a clean kit."""
    spec = importlib.util.spec_from_file_location(
        "generate_domain_kit", REPO / "scripts" / "generate_domain_kit.py"
    )
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)

    domain = next(
        d for d in gen.DOMAIN_CATALOG
        if d not in gen.SKIP_KITS and not (REPO / "block_store" / "kits" / d).exists()
    )
    kits = tmp_path / "kits"
    kits.mkdir()
    monkeypatch.setattr(gen, "KITS_DIR", kits)
    gen.generate_domain_kit(domain, quiet=True)

    manifest = json.loads((kits / domain / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["flow"] == "independent", (
        "the generator emitted a kit with no composition declaration; that is "
        "how the existing 18 gaps were created"
    )
    codes = [c for c, _ in audit.audit_kit(domain, str(kits), set(manifest["blocks"]))]
    assert "no_composition" not in codes
