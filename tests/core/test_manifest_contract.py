"""The contract fields on ``block.json``, and the proof they cost nothing.

Three properties.

**Every field is optional.** All 114 manifests in this repo declare none of
them and all 114 still validate. Absence is never an error in this phase.

**A declared field is checked.** A half-filled ``requires_inputs`` is worse
than an absent one: a planner that reads an entry with no type will either
guess or crash, and both are worse than knowing the block never said.

**No signature moved.** The fields are stripped before the manifest is
hashed, the way #84 stripped ``trust_tier``. Every stored digest is
recomputed here and compared.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.block_result import STATUSES
from app.core.manifest_contract import (
    BRIEF_SCOPE_FAIL_CLOSED,
    BRIEF_SCOPE_KEYS,
    CAPABILITY_CLASS,
    CAPABILITY_CLASSES,
    CONTRACT_MANIFEST_KEYS,
    ENSURE_SCOPES,
    FACTORY_ATTACH,
    check_capability_class,
    check_factory_attach,
    DECLARED_TYPES,
    PRECONDITION_KINDS,
    SCOPE_RESOURCE_KINDS,
    TRAINING_ELIGIBILITY_POLICY,
    VERTICAL_SCOPE_KEYS,
    vertical_scope_errors,
    check_acceptance,
    check_brief_scope_fields,
    check_contract_fields,
    check_failure_modes,
    check_kill_switch,
    check_never,
    check_preconditions,
    check_produces,
    check_reads,
    check_requires_inputs,
    check_source_commit,
    check_writes,
    declared_brief_scope_fields,
    declared_contract_fields,
    missing_brief_scope_fields,
)

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "block_registry"

_ALL_MANIFESTS = sorted(
    list(REGISTRY.glob("*/block.json"))
    + list(ROOT.glob("block_store/kits/*/bundle/block_registry/*/block.json"))
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# -- every field is optional ----------------------------------------------


def test_the_repo_has_manifests_to_check():
    """Guards the two sweeps below: an empty glob would pass them silently."""
    assert len(_ALL_MANIFESTS) >= 114, len(_ALL_MANIFESTS)


@pytest.mark.parametrize(
    "manifest_path", _ALL_MANIFESTS, ids=lambda p: p.parent.name
)
def test_every_current_manifest_still_validates_unchanged(manifest_path: Path):
    """The non-breaking claim, stated once per manifest."""
    manifest = _load(manifest_path)
    assert check_contract_fields(manifest) == []
    assert check_brief_scope_fields(manifest) == []


def test_every_store_registry_manifest_declares_brief_scope_fields():
    """Backfill pin: Factory inventory is a registry query, not a guess.

    Empty lists are allowed (measured nothing / could not measure).
    Missing keys are the leftovers Lane 2 reports.
    """
    store = sorted(REGISTRY.glob("*/block.json"))
    assert len(store) >= 100, len(store)
    leftovers = []
    for path in store:
        missing = missing_brief_scope_fields(_load(path))
        if missing:
            leftovers.append((path.parent.name, missing))
    assert leftovers == []


def test_an_empty_manifest_declares_nothing_and_that_is_fine():
    assert check_contract_fields({}) == []
    assert declared_contract_fields({}) == []


def test_version_and_trust_tier_are_not_redefined_here():
    """Both already exist and are already required. A second definition of an
    accepted-value set is the drift AGENTS.md warns about."""
    assert "version" not in CONTRACT_MANIFEST_KEYS
    assert "trust_tier" not in CONTRACT_MANIFEST_KEYS


def test_learning_engine_training_eligibility_is_independently_labeled_only():
    """Strict: only independently labeled samples may train."""
    manifest = _load(REGISTRY / "learning_engine" / "block.json")
    assert manifest.get("provenance_policy") == TRAINING_ELIGIBILITY_POLICY
    assert check_contract_fields(manifest) == []


def test_a_null_field_is_not_the_same_as_an_absent_one():
    """Omitting a field says "not declared". Setting it to null says "declared
    as nothing", which no reader can act on."""
    assert check_contract_fields({"kill_switch": None})
    assert check_contract_fields({}) == []


# -- what a declared field must look like ---------------------------------


def test_requires_inputs_accepts_a_well_formed_declaration():
    assert (
        check_requires_inputs(
            [
                {"name": "boq_file", "type": "file", "required": True},
                {"name": "rate_table", "type": "json", "required": False},
            ]
        )
        == []
    )


@pytest.mark.parametrize(
    "bad,expected",
    [
        ("not a list", "must be a list"),
        ([["nested"]], "must be an object"),
        ([{"type": "file"}], "has no name"),
        ([{"name": "boq"}], "declares no type"),
        ([{"name": "boq", "type": "spreadsheet"}], "unknown type"),
        ([{"name": "boq", "type": "file", "required": "yes"}], "non-boolean"),
    ],
)
def test_a_half_filled_requires_inputs_is_refused(bad, expected):
    reasons = check_requires_inputs(bad)
    assert reasons, "a malformed declaration passed"
    assert any(expected in reason for reason in reasons), reasons


def test_the_type_vocabulary_is_the_one_the_store_already_uses():
    """Taken from the 114 manifests rather than invented. Untidy on purpose:
    normalising list/array and text/string would mean rewriting existing
    manifests, which this lane does not do."""
    for observed in ("json", "string", "boolean", "number", "file", "array"):
        assert observed in DECLARED_TYPES
    assert {"list", "text"} <= DECLARED_TYPES


def test_produces_uses_the_same_shape_as_requires_inputs():
    assert check_produces([{"name": "priced_boq", "type": "json"}]) == []
    assert check_produces([{"name": "priced_boq"}])


def test_a_precondition_must_name_something_checkable():
    assert (
        check_preconditions([{"kind": "index", "ref": "project_corpus"}]) == []
    )
    reasons = check_preconditions([{"kind": "index"}])
    assert any("names no ref" in reason for reason in reasons), reasons


def test_the_precondition_kinds_cover_what_the_spec_named():
    assert {"team", "file", "index"} <= PRECONDITION_KINDS


def test_an_unknown_precondition_kind_is_refused():
    reasons = check_preconditions([{"kind": "vibes", "ref": "x"}])
    assert any("unknown kind" in reason for reason in reasons), reasons


# -- failure modes, tied to the BlockResult statuses ----------------------


def test_a_failure_mode_names_the_status_it_surfaces_as():
    assert (
        check_failure_modes(
            [
                {"mode": "rate_table_missing", "status": "refused"},
                {"mode": "ocr_below_threshold", "status": "partial"},
            ]
        )
        == []
    )


def test_a_failure_mode_that_reports_ok_is_the_defect_this_field_catches():
    """A declared failure that surfaces as success is the ~24-in-100 class:
    a failure that still looks like an answer."""
    reasons = check_failure_modes([{"mode": "quietly_returns_zero", "status": "ok"}])
    assert any("failure mode that reports success" in r for r in reasons), reasons


def test_a_failure_mode_status_outside_the_block_result_set_is_refused():
    reasons = check_failure_modes([{"mode": "x", "status": "degraded"}])
    assert any("not a BlockResult status" in r for r in reasons), reasons


def test_the_failure_mode_statuses_come_from_block_result_not_a_local_copy():
    """One definition of the four statuses, or a manifest passes one checker
    and fails another."""
    for status in STATUSES - {"ok"}:
        assert check_failure_modes([{"mode": "m", "status": status}]) == []


# -- kill switch and source commit ----------------------------------------


def test_kill_switch_is_an_env_var_name():
    assert check_kill_switch("CEREBRUM_DISABLE_BOQ_PROCESSOR") == []


@pytest.mark.parametrize("bad", ["", "   ", "lower_case", "HAS-DASH", 42, None])
def test_kill_switch_refuses_anything_that_is_not_a_name(bad):
    assert check_kill_switch(bad)


def test_source_commit_wants_a_repo_and_a_sha():
    assert (
        check_source_commit({"repo": "bopoadz-del/The_Fork", "sha": "60f3765"}) == []
    )


@pytest.mark.parametrize(
    "bad",
    [
        {"sha": "60f3765"},
        {"repo": "bopoadz-del/The_Fork"},
        {"repo": "bopoadz-del/The_Fork", "sha": "not-a-sha"},
        {"repo": "bopoadz-del/The_Fork", "sha": "abc"},
        "60f3765",
    ],
)
def test_source_commit_refuses_a_provenance_claim_nobody_can_follow(bad):
    assert check_source_commit(bad)


def test_declared_contract_fields_reports_what_a_manifest_adopted():
    manifest = {
        "id": "x",
        "kill_switch": "CEREBRUM_DISABLE_X",
        "produces": [{"name": "y", "type": "json"}],
    }
    assert declared_contract_fields(manifest) == ["produces", "kill_switch"]


# -- the signature ---------------------------------------------------------


def test_every_declared_field_is_inside_the_signed_digest():
    """Nothing a block declares can be edited without re-signing.

    The contract, brief-scope (reads/writes/never/acceptance), vertical and
    trust-tier fields used to be stripped before hashing because the
    operator's key was out of reach. The key is now held
    (cerebrum/store-signing), every manifest was re-signed, and a declaration
    the Factory derives decisions from -- e.g. a read of the vector store --
    is covered by the signature.
    """
    from app.core.publisher_registry import BlockSigner

    base = {
        "id": "demo",
        "name": "Demo",
        "version": "1.0.0",
        "publisher_id": "cerebrum_platform",
        "permissions": {},
    }
    missing = Path("does-not-exist")
    before = BlockSigner._compute_digests(missing, base)["block.json"]
    declared = set(CONTRACT_MANIFEST_KEYS) | set(BRIEF_SCOPE_KEYS) | set(VERTICAL_SCOPE_KEYS) | {"trust_tier"}
    for key in sorted(declared):
        moved = BlockSigner._compute_digests(missing, {**base, key: ["zorblat"]})["block.json"]
        assert moved != before, f"{key} is outside the signature"
    # Only the outputs of signing are excluded.
    same = BlockSigner._compute_digests(missing, {**base, "signature": {"x": 1}, "digests": {"y": 2}})["block.json"]
    assert same == before

def test_brief_scope_is_report_only_until_the_flip():
    """The fail-closed flip is a separate owner-gated PR."""
    assert BRIEF_SCOPE_FAIL_CLOSED is False
    assert BRIEF_SCOPE_KEYS == ("reads", "writes", "never", "acceptance")


def test_empty_brief_scope_lists_are_valid_measured_nothing():
    assert check_brief_scope_fields(
        {"reads": [], "writes": [], "never": [], "acceptance": []}
    ) == []
    assert missing_brief_scope_fields(
        {"reads": [], "writes": [], "never": [], "acceptance": []}
    ) == []


def test_missing_brief_scope_fields_are_the_backfill_leftovers():
    assert missing_brief_scope_fields({}) == list(BRIEF_SCOPE_KEYS)
    assert declared_brief_scope_fields({"reads": []}) == ["reads"]


def test_reads_writes_never_require_a_kind_and_a_scope():
    assert check_reads([{"kind": "file", "scope": "input_pdf"}]) == []
    assert check_writes([{"kind": "database", "scope": "sql"}]) == []
    assert check_never([{"kind": "network", "scope": "outbound"}]) == []
    assert check_reads([{"kind": "file"}])
    assert check_writes([{"kind": "vibes", "scope": "x"}])


def test_the_scope_kinds_cover_what_the_store_actually_touches():
    assert {"file", "network", "database", "secrets", "llm"} <= SCOPE_RESOURCE_KINDS
    assert {"team", "index", "block"} <= SCOPE_RESOURCE_KINDS


def test_acceptance_is_a_fail_loud_check_tied_to_block_result():
    assert (
        check_acceptance(
            [
                {
                    "id": "missing_pdf",
                    "check": "refuses when no PDF is provided",
                    "status": "refused",
                }
            ]
        )
        == []
    )
    reasons = check_acceptance(
        [{"id": "quiet", "check": "returns zero", "status": "ok"}]
    )
    assert any("reports success" in reason for reason in reasons), reasons


def test_a_null_brief_scope_field_is_not_the_same_as_an_absent_one():
    assert check_brief_scope_fields({"reads": None})
    assert check_brief_scope_fields({}) == []


@pytest.mark.parametrize(
    "manifest_path",
    [p for p in _ALL_MANIFESTS if (_load(p).get("digests") or {}).get("block.json")],
    ids=lambda p: p.parent.name,
)
def test_no_stored_digest_moved(manifest_path: Path):
    """Every stored digest is the digest of the manifest as it stands.

    Every declared field is signed, so editing any of them without
    re-signing (scripts/rotate_publisher_key.py --private-key ...) fails
    here and in test_signing_operational.
    """
    from app.core.publisher_registry import BlockSigner

    manifest = _load(manifest_path)
    stored = manifest["digests"]["block.json"]
    recomputed = BlockSigner._compute_digests(
        manifest_path.parent, manifest, normalize_eol="\n"
    )["block.json"]

    assert recomputed == stored


def test_adding_a_contract_field_moves_the_digest():
    """Stated directly: a contract field is signed."""
    from app.core.publisher_registry import BlockSigner

    base = {
        "id": "demo",
        "name": "Demo",
        "version": "1.0.0",
        "publisher_id": "cerebrum_platform",
        "trust_tier": "platform",
        "permissions": {},
    }
    enriched = {
        **base,
        "requires_inputs": [{"name": "boq_file", "type": "file", "required": True}],
        "produces": [{"name": "priced_boq", "type": "json"}],
        "preconditions": [{"kind": "index", "ref": "project_corpus"}],
        "failure_modes": [{"mode": "rate_table_missing", "status": "refused"}],
        "kill_switch": "CEREBRUM_DISABLE_DEMO",
        "source_commit": {"repo": "bopoadz-del/The_Fork", "sha": "60f3765"},
        "provenance_policy": "every figure must appear in retrieved context",
        "capability_class": "orchestration",
        "factory_attach": {"cleared": False, "reason": "serves its own"},
    }
    missing = Path("does-not-exist")

    before = BlockSigner._compute_digests(missing, base)["block.json"]
    after = BlockSigner._compute_digests(missing, enriched)["block.json"]

    assert before != after
    assert set(enriched) - set(base) == set(CONTRACT_MANIFEST_KEYS)


def test_adding_brief_scope_fields_moves_the_digest():
    """Brief scope (reads/writes/never/acceptance) is signed."""
    from app.core.publisher_registry import BlockSigner

    base = {
        "id": "demo",
        "name": "Demo",
        "version": "1.0.0",
        "publisher_id": "cerebrum_platform",
        "trust_tier": "platform",
        "permissions": {},
    }
    enriched = {
        **base,
        "reads": [{"kind": "file", "scope": "input_pdf"}],
        "writes": [{"kind": "caller", "scope": "output"}],
        "never": [{"kind": "secrets", "scope": "vault"}],
        "acceptance": [
            {
                "id": "missing_pdf",
                "check": "refuses when no PDF is provided",
                "status": "refused",
            }
        ],
    }
    missing = Path("does-not-exist")
    before = BlockSigner._compute_digests(missing, base)["block.json"]
    after = BlockSigner._compute_digests(missing, enriched)["block.json"]
    assert before != after
    assert set(enriched) - set(base) == set(BRIEF_SCOPE_KEYS)


# -- the audit script sees the same rules ---------------------------------


def test_the_audit_script_loads_the_same_checker():
    """``scripts/audit_block_standards.py`` cannot import ``app.core`` (that
    package pulls the API stack), so it loads this module by path. If that
    load breaks, the audit silently stops checking contract fields."""
    import importlib.util

    path = ROOT / "scripts" / "audit_block_standards.py"
    spec = importlib.util.spec_from_file_location("audit_block_standards", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.CONTRACT_MANIFEST_KEYS == CONTRACT_MANIFEST_KEYS
    assert module.BRIEF_SCOPE_KEYS == BRIEF_SCOPE_KEYS
    assert module.BRIEF_SCOPE_FAIL_CLOSED is False
    assert module.check_contract_fields({"kill_switch": "lower"}), (
        "the audit loaded the module but is not calling the checker"
    )
    warnings = module.audit_block(ROOT / "block_registry" / "pdf")
    # Report-only: missing brief-scope fields must not fail-close the store.
    assert not any("brief-scope" in err for err in warnings["errors"])


# -- vertical scope --------------------------------------------------------
#
# Every platform the Factory builds is built for a vertical. A block that
# declares ``verticals`` is eligible only for blueprints in one of them.


_SCOPED = ("contract_retrieval", "drawing_qto", "formula_executor_v2")
_OWNER_DECLARED = {"construction", "interior_design", "architecture", "facility_management"}


@pytest.mark.parametrize("block_id", _SCOPED)
def test_the_three_construction_family_blocks_declare_their_verticals(block_id):
    """Owner, 2026-09-21: these attach to construction, interior design,
    architecture and facility management platforms -- "only these four"."""
    manifest = json.loads(
        (ROOT / "block_registry" / block_id / "block.json").read_text(encoding="utf-8")
    )

    assert vertical_scope_errors(manifest) == []
    assert _OWNER_DECLARED <= set(manifest["verticals"])
    # Anything beyond the four may only be another spelling of one of them.
    assert set(manifest["verticals"]) - _OWNER_DECLARED <= {"facilities_management"}


@pytest.mark.parametrize("block_id", _SCOPED)
def test_adding_the_field_did_not_invalidate_the_signature(block_id):
    """``verticals`` is inside the signature, and the real manifests that
    declare it verify against the registry key -- proven on the manifests,
    not a fixture."""
    from app.core.publisher_registry import BlockVerifier

    result = BlockVerifier().verify_block(ROOT / "block_registry" / block_id)

    assert result["verified"] is True, result


def test_a_block_that_declares_nothing_is_eligible_everywhere():
    assert vertical_scope_errors({"id": "x"}) == []


@pytest.mark.parametrize(
    "value",
    [[], "construction", ["Construction"], ["interior design"], ["a", "a"], [7], None],
)
def test_a_malformed_scope_is_refused(value):
    """An EMPTY list is refused rather than read as "no vertical at all": a
    block nothing can ever attach is never what a blank list meant."""
    assert vertical_scope_errors({"id": "x", "verticals": value})


# -- dispatch declarations: what the Factory branches on instead of an id --


def test_a_capability_class_is_one_word_from_the_vocabulary():
    assert check_capability_class("orchestration") == []
    reasons = check_capability_class("pipeline-ish")
    assert reasons and CAPABILITY_CLASS in reasons[0], reasons
    assert check_capability_class(None)


def test_no_capability_class_is_spelled_like_a_block_id():
    # A class equal to an id would let a consumer branch on the id while
    # claiming to read the class.
    ids = {_load(p).get("id") for p in REGISTRY.glob("*/block.json")}
    assert not (CAPABILITY_CLASSES & ids)


def test_a_factory_refusal_must_say_why():
    assert check_factory_attach({"cleared": True}) == []
    assert check_factory_attach({"cleared": False, "reason": "serves its own"}) == []
    assert check_factory_attach({"cleared": False})
    assert check_factory_attach({"cleared": "no", "reason": "x"})
    assert check_factory_attach(["cleared"])


def test_a_requires_input_may_name_the_fields_that_satisfy_it():
    ok = [{"name": "attachment_path", "type": "string", "required": False,
           "satisfied_by": ["pdf_path", "text"], "why": "parses a document"}]
    assert check_requires_inputs(ok) == []
    bad = [{"name": "attachment_path", "type": "string", "satisfied_by": []}]
    assert any("satisfied_by" in r for r in check_requires_inputs(bad))


def test_an_ensured_precondition_carries_everything_a_caller_needs():
    whole = {"kind": "team", "ref": "team_id", "scope": "platform",
             "ensure": "create_team", "ensure_input": ["user_id"],
             "carry": "team_id", "into": ["get_team"], "why": "mints the id"}
    assert check_preconditions([whole]) == []
    for key in ("carry", "into", "ensure_input", "why"):
        half = {k: v for k, v in whole.items() if k != key}
        assert any(key in r for r in check_preconditions([half])), key
    assert any("scope" in r for r in check_preconditions([{**whole, "scope": "boot"}]))
    assert ENSURE_SCOPES == {"platform", "per_record"}


@pytest.mark.parametrize(
    "path",
    [p for p in _ALL_MANIFESTS
     if {CAPABILITY_CLASS, FACTORY_ATTACH, "preconditions", "requires_inputs"} & set(_load(p))],
    ids=lambda p: p.parent.name,
)
def test_every_declared_dispatch_field_validates(path: Path):
    assert check_contract_fields(_load(path)) == []
