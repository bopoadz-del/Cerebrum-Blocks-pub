"""The reference corpus: shared, read-only, and never answering as a tenant's own.

The properties asserted are the ones that decide whether a shared corpus is safe to
have at all:

  * a document with no provenance cannot enter it
  * a TENANT-ONLY licence can never enter it, however else it is labelled
  * a mirror is not a citation
  * it is structurally out of the always-on merge, even when a stale config lists it
  * a named-asset query never reaches it, and a caller who does not say is assumed
    to be asking about one
"""
from __future__ import annotations

import pytest

from app.blocks.reference_corpus import (
    LICENCES_ADMITTED,
    REFERENCE_PREFIX,
    REQUIRED_INGEST_FIELDS,
    ReferenceCorpusBlock,
    admit,
    is_reference_project,
    label_chunks,
    plan,
    refused_host,
)

#: A real Tier-1 source from the owner's list, so the gate is exercised against the
#: documents it will actually meet rather than a fixture shaped to pass.
NAO_LONDON_2012 = {
    "source_class": "government_audit",
    "publisher": "UK National Audit Office",
    "url": "https://www.nao.org.uk/wp-content/uploads/2012/12/1213794fr.pdf",
    "sha256": "b" * 64,
    "event": "London 2012",
    "edition_year": 2012,
    "licence": "open",
}

REF = f"{REFERENCE_PREFIX}mega_event_history"


@pytest.fixture
def block():
    return ReferenceCorpusBlock()


async def _run(block, payload):
    return await block.process(payload, {})


# ── admission ─────────────────────────────────────────────────────────────

def test_a_real_government_audit_is_admitted():
    assert admit(NAO_LONDON_2012, project_id=REF)["admitted"] is True


@pytest.mark.parametrize("field", REQUIRED_INGEST_FIELDS)
def test_every_required_field_is_required(field):
    """An unlabelled document in a shared corpus is a figure with no provenance that
    every tenant can reach."""
    document = {k: v for k, v in NAO_LONDON_2012.items() if k != field}
    verdict = admit(document, project_id=REF)
    assert verdict["admitted"] is False
    assert any(field in reason for reason in verdict["reasons"])


def test_a_tenant_only_licence_can_never_enter_the_shared_corpus():
    """The SGSA Green Guide: the purchase licence is personal to the individual and
    allows three downloads. Admitting it would put one person's licensed copy in
    front of every tenant."""
    green_guide = dict(
        NAO_LONDON_2012,
        publisher="Sports Grounds Safety Authority",
        url="https://sgsa.org.uk/greenguide-availablenow/",
        event="n/a",
        licence="tenant_only",
    )
    verdict = admit(green_guide, project_id=REF)
    assert verdict["admitted"] is False
    reason = " ".join(verdict["reasons"])
    assert "tenant-only" in reason and "tenant-supplied" in reason
    assert "tenant_only" not in LICENCES_ADMITTED


def test_an_unrecognised_licence_is_refused_rather_than_assumed_permissive():
    verdict = admit(dict(NAO_LONDON_2012, licence="probably-fine"), project_id=REF)
    assert verdict["admitted"] is False
    assert "not a permissive one" in " ".join(verdict["reasons"])


@pytest.mark.parametrize("url,host", [
    ("https://www.scribd.com/document/123/nao-london-2012", "scribd.com"),
    ("https://fr.slideshare.net/slideshow/x", "slideshare.net"),
    ("https://coursehero.com/file/9/", "coursehero.com"),
])
def test_a_mirror_is_not_a_citation(url, host):
    verdict = admit(dict(NAO_LONDON_2012, url=url), project_id=REF)
    assert verdict["admitted"] is False
    assert host in " ".join(verdict["reasons"])


def test_a_publisher_whose_path_mentions_a_mirror_is_not_refused():
    """Matched on the registered domain, not a substring: an official URL that
    happens to contain the word is still the official URL."""
    assert refused_host("https://www.nao.org.uk/reports/scribd.com-comparison.pdf") is None
    assert refused_host("https://cdn.scribd.com/x") == "scribd.com"


def test_a_digest_that_is_not_a_digest_is_refused():
    verdict = admit(dict(NAO_LONDON_2012, sha256="not-a-hash"), project_id=REF)
    assert verdict["admitted"] is False
    assert "provably the document we cited" in " ".join(verdict["reasons"])


def test_a_document_cannot_be_admitted_into_a_tenant_project():
    """The prefix is reserved so a tenant cannot write into the shared corpus by
    naming itself."""
    verdict = admit(NAO_LONDON_2012, project_id="venue-42")
    assert verdict["admitted"] is False
    assert REFERENCE_PREFIX in " ".join(verdict["reasons"])
    assert is_reference_project("venue-42") is False
    assert is_reference_project(REF) is True


# ── the retrieval plan ────────────────────────────────────────────────────

def test_a_named_asset_query_is_answered_from_tenant_chunks_only():
    result = plan({"project_id": "venue-42", "include_reference": [REF],
                   "named_asset": True})["result"]
    assert result["reference_permitted"] is False
    assert "another venue's audit is not this venue's figure" in result["why"]


def test_a_general_question_may_reach_the_reference_as_a_disclosed_fallback():
    result = plan({"project_id": "venue-42", "include_reference": [REF],
                   "named_asset": False})["result"]
    assert result["reference_permitted"] is True
    assert result["reference_is_fallback_only"] is True
    assert "DISCLOSED fallback" in result["why"]


def test_a_caller_that_does_not_say_is_assumed_to_be_asking_about_a_named_asset():
    """Ambiguity resolves toward the tenant's own documents. Reference is opt-in and
    fallback-only, so the safe default is the narrower one."""
    result = plan({"project_id": "venue-42", "include_reference": [REF]})["result"]
    assert result["named_asset_query"] is True
    assert result["reference_permitted"] is False


def test_the_reference_corpus_is_structurally_out_of_the_always_on_merge():
    """The property this block delegates rather than restates: STEP 0 in
    rag_tenant_isolation removes a fallback corpus from the merge even when a stale
    config still lists it. One rule with one test beats two that agree today."""
    result = plan({
        "project_id": "venue-42",
        "gk_projects": ["training_material", REF],
        "include_reference": [REF],
        "named_asset": False,
    })["result"]
    assert REF not in result["tenant_projects"]
    assert "training_material" in result["tenant_projects"]
    assert result["reference_projects"] == [REF]


def test_retrieval_without_a_tenant_scope_is_refused():
    assert plan({})["status"] == "refused"
    assert "project_id is required" in plan({})["error"]


def test_a_query_is_never_asked_as_the_reference_corpus():
    refusal = plan({"project_id": REF})
    assert refusal["status"] == "refused"
    assert "not a tenant" in refusal["error"]


def test_include_reference_must_name_reference_corpora():
    refusal = plan({"project_id": "venue-42", "include_reference": ["some-other-tenant"]})
    assert refusal["status"] == "refused"
    assert "some-other-tenant" in refusal["error"]


# ── labelling ─────────────────────────────────────────────────────────────

def test_every_chunk_is_labelled_by_the_corpus_it_came_from():
    """An unlabelled chunk reads as the tenant's own document once it is in an
    answer, and nothing downstream can tell otherwise."""
    labelled = label_chunks([
        {"project_id": "venue-42", "text": "our barrier cert"},
        {"project_id": REF, "text": "London 2012 outturn"},
        {"text": "no project at all"},
    ])
    assert [c["corpus"] for c in labelled] == ["tenant", "reference", "tenant"]


# ── the block surface ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_block_refuses_an_unknown_action(block):
    out = await _run(block, {"action": "delete_everything"})
    assert out["status"] == "refused"
    assert "plan, admit or label" in out["error"]


@pytest.mark.asyncio
async def test_the_block_admits_and_refuses_through_process(block):
    ok = await _run(block, {"action": "admit", "project_id": REF,
                            "document": NAO_LONDON_2012})
    assert ok["status"] == "ok"
    assert "government_audit" in ok["detail"]

    no = await _run(block, {"action": "admit", "project_id": REF,
                            "document": dict(NAO_LONDON_2012, licence="tenant_only")})
    assert no["status"] == "refused"
    assert no["result"]["admitted"] is False


@pytest.mark.asyncio
async def test_the_block_counts_what_came_from_where(block):
    out = await _run(block, {"action": "label", "chunks": [
        {"project_id": "venue-42"}, {"project_id": REF}, {"project_id": REF}]})
    assert out["result"]["tenant_count"] == 1
    assert out["result"]["reference_count"] == 2


@pytest.mark.asyncio
async def test_a_non_mapping_document_is_refused_not_coerced(block):
    out = await _run(block, {"action": "admit", "project_id": REF, "document": "a pdf"})
    assert out["status"] == "refused"


# ── the registry adapter path ─────────────────────────────────────────────

def _adapter():
    import importlib.util
    import pathlib

    spec = importlib.util.spec_from_file_location(
        "reference_corpus_adapter",
        pathlib.Path(__file__).resolve().parents[2]
        / "block_registry" / "reference_corpus" / "block.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_registry_adapter_returns_the_result_not_a_nested_envelope():
    """The adapter calls `execute`. The INHERITED execute wraps whatever `process`
    returns in a second envelope, so the adapter received an envelope whose `result`
    was another envelope — and a certification that guts `process` would then be
    measuring a wrapper that does not care what `process` said."""
    result = _adapter().run(input={
        "action": "plan", "project_id": "venue-42",
        "include_reference": [REF], "named_asset": False})

    assert "reference_permitted" in result, (
        f"the adapter returned a nested envelope: {sorted(result)}")
    assert result["reference_permitted"] is True
    assert result["reference_is_fallback_only"] is True


def test_the_registry_adapter_raises_on_a_refusal_rather_than_returning_it():
    """A refusal that comes back as a value gets used as one."""
    with pytest.raises(RuntimeError) as exc:
        _adapter().run(input={
            "action": "admit", "project_id": REF,
            "document": dict(NAO_LONDON_2012, licence="tenant_only")})
    assert "tenant" in str(exc.value).lower()


def test_the_registry_entry_declares_what_this_block_never_touches():
    """`never` is a RESOURCE declaration, and a planner that reads no corpus and
    reaches no network should say so. The prose prohibitions live in `acceptance`,
    where each one is a checkable claim."""
    import json
    import pathlib

    manifest = json.loads((
        pathlib.Path(__file__).resolve().parents[2]
        / "block_registry" / "reference_corpus" / "block.json"
    ).read_text(encoding="utf-8"))

    never = {(e["kind"], e["scope"]) for e in manifest["never"]}
    assert ("network", "any") in never
    assert ("index", "corpus") in never
    assert manifest["permissions"]["network"] is False

    claims = {a["id"] for a in manifest["acceptance"]}
    assert {"licence_gate", "provenance_required", "mirror_refused",
            "named_asset_tenant_only", "never_in_the_always_on_merge",
            "reserved_prefix"} <= claims
    # Every acceptance status is a BlockResult status, not an invariant severity.
    assert {a["status"] for a in manifest["acceptance"]} <= {"failed", "partial", "refused"}


def test_the_block_is_signed_and_verifies():
    import pathlib

    from app.core.publisher_registry import BlockVerifier, PublisherRegistry

    verdict = BlockVerifier(registry=PublisherRegistry(path=None)).verify_block(
        block_path=pathlib.Path(__file__).resolve().parents[2]
        / "block_registry" / "reference_corpus",
        publisher_id=None)
    assert verdict["verified"] is True, verdict.get("reason")
