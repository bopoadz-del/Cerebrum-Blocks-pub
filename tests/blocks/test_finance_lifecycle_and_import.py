"""Finance cluster: CoA lifecycle gate + finance_import file/idempotency entry."""

from __future__ import annotations

import asyncio
import csv

from app.blocks.finance_coa_governance import FinanceCoAGovernanceBlock
from app.blocks.finance_import import FinanceImportBlock


def _run(block, **data):
    return asyncio.run(block.process(dict(data), params={}))


GOOD_ACCOUNTS = [
    {"account_id": "1000", "parent_id": None, "name": "Assets"},
    {"account_id": "1100", "parent_id": "1000", "name": "Cash"},
]

GL_ROW = {
    "line_id": "L1",
    "legal_entity": "LE1",
    "gl_account": "4000",
    "net_amount": "10.00",
    "currency_code": "USD",
    "posting_date": "2026-01-15",
}


# -- CoA lifecycle ---------------------------------------------------------


def test_coa_lifecycle_draft_propose_approve_activates():
    block = FinanceCoAGovernanceBlock()
    draft = _run(
        block,
        operation="create_draft",
        coa_id="acme",
        requester="fp&a_manager",
        accounts=GOOD_ACCOUNTS,
    )
    assert draft["status"] == "success"
    assert draft["status_of_draft"] == "draft"
    assert draft["version"] == 1

    proposed = _run(block, operation="propose_activation", draft_id=draft["draft_id"])
    assert proposed["approval_required"] is True

    approved = _run(
        block,
        operation="approve_activation",
        draft_id=draft["draft_id"],
        approver="controller",
    )
    assert approved["status"] == "success"
    assert approved["version"] == 1

    state = _run(block, operation="state")
    assert state["active"]["acme"]["version"] == 1
    assert state["active"]["acme"]["approved_by"] == "controller"


def test_coa_self_approval_is_refused():
    block = FinanceCoAGovernanceBlock()
    draft = _run(
        block,
        operation="create_draft",
        coa_id="acme",
        requester="fp&a_manager",
        accounts=GOOD_ACCOUNTS,
    )
    _run(block, operation="propose_activation", draft_id=draft["draft_id"])
    out = _run(
        block,
        operation="approve_activation",
        draft_id=draft["draft_id"],
        approver="fp&a_manager",
    )
    assert out["status"] == "validation_error"
    assert "self_approval refused" in out["error"]


def test_coa_approval_without_proposal_is_refused():
    block = FinanceCoAGovernanceBlock()
    draft = _run(
        block,
        operation="create_draft",
        coa_id="acme",
        requester="fp&a_manager",
        accounts=GOOD_ACCOUNTS,
    )
    out = _run(
        block,
        operation="approve_activation",
        draft_id=draft["draft_id"],
        approver="controller",
    )
    assert out["status"] == "validation_error"
    assert "propose_activation first" in out["error"]


def test_coa_draft_with_broken_hierarchy_is_refused():
    block = FinanceCoAGovernanceBlock()
    out = _run(
        block,
        operation="create_draft",
        coa_id="acme",
        requester="fp&a_manager",
        accounts=[
            {"account_id": "1100", "parent_id": "9999", "name": "Orphan"},
        ],
    )
    assert out["status"] == "validation_error"
    assert "draft refused by validation" in out["error"]


def test_coa_versioning_archives_previous():
    block = FinanceCoAGovernanceBlock()
    d1 = _run(
        block,
        operation="create_draft",
        coa_id="acme",
        requester="fp&a_manager",
        accounts=GOOD_ACCOUNTS,
    )
    _run(block, operation="propose_activation", draft_id=d1["draft_id"])
    _run(
        block,
        operation="approve_activation",
        draft_id=d1["draft_id"],
        approver="controller",
    )
    d2 = _run(
        block,
        operation="create_draft",
        coa_id="acme",
        requester="fp&a_manager",
        accounts=GOOD_ACCOUNTS
        + [{"account_id": "1200", "parent_id": "1000", "name": "Receivables"}],
    )
    assert d2["version"] == 2
    _run(block, operation="propose_activation", draft_id=d2["draft_id"])
    approved = _run(
        block,
        operation="approve_activation",
        draft_id=d2["draft_id"],
        approver="cfo",
    )
    assert approved["archived_previous"] is True
    assert approved["previous_version"] == 1


# -- finance_import file + idempotency -------------------------------------


def test_parse_csv_file_and_normalize(tmp_path):
    block = FinanceImportBlock()
    csv_file = tmp_path / "gl.csv"
    with csv_file.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["line_id", "legal_entity", "gl_account", "net_amount", "currency_code", "posting_date"])
        writer.writerow(["L1", "LE1", "4000", "123.45", "USD", "2026-01-15"])
    out = _run(block, operation="parse_file", file_path=str(csv_file), source_type="gl")
    assert out["status"] == "success"
    assert out["accepted"][0]["record_id"] == "L1"


def test_parse_file_missing_or_bad_extension(tmp_path):
    block = FinanceImportBlock()
    missing = _run(block, operation="parse_file", file_path=str(tmp_path / "nope.csv"), source_type="gl")
    assert missing["status"] == "validation_error"
    assert "file not found" in missing["error"]

    txt = tmp_path / "data.txt"
    txt.write_text("x")
    bad_ext = _run(block, operation="parse_file", file_path=str(txt), source_type="gl")
    assert bad_ext["status"] == "validation_error"
    assert "unsupported file type" in bad_ext["error"]


def test_ingest_is_idempotent_per_batch_and_record():
    block = FinanceImportBlock()
    rows = [GL_ROW, {**GL_ROW, "line_id": "L2", "net_amount": "20.00"}]
    first = _run(block, operation="ingest", rows=rows, source_type="gl")
    assert first["accepted"] == 2
    assert first["duplicates"] == 0
    assert first["already_ingested"] is False

    same_batch = _run(block, operation="ingest", rows=rows, source_type="gl")
    assert same_batch["already_ingested"] is True
    assert same_batch["accepted"] == 0
    assert same_batch["duplicates"] == 2

    overlap = _run(
        block,
        operation="ingest",
        rows=[GL_ROW, {**GL_ROW, "line_id": "L3", "net_amount": "30.00"}],
        source_type="gl",
    )
    assert overlap["accepted"] == 1
    assert overlap["duplicates"] == 1


def test_ingest_reset_clears_the_ledger():
    block = FinanceImportBlock()
    _run(block, operation="ingest", rows=[GL_ROW], source_type="gl")
    _run(block, operation="reset_ingest")
    again = _run(block, operation="ingest", rows=[GL_ROW], source_type="gl")
    assert again["already_ingested"] is False
    assert again["accepted"] == 1
