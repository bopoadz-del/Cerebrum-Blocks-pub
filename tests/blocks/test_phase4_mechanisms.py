"""Phase 4 mechanisms: scope refusal, source precedence, revision currency."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.blocks import _knowledge as kb
from app.core.credibility import CredibilityTier
from app.core.grounding import check_scope_refusal, verdict_log_path


# ---------------------------------------------------------------------------
# Scope refusal — questions never to attempt, even when perfectly grounded.
# ---------------------------------------------------------------------------


class TestScopeRefusal:
    def test_medication_dosing_is_refused(self):
        hit = check_scope_refusal("What morphine dose should I administer to the patient?")
        assert hit is not None
        assert hit["reason"]

    def test_structural_signoff_is_refused(self):
        hit = check_scope_refusal(
            "Can you certify that this beam design is structurally adequate for sign-off?"
        )
        assert hit is not None

    def test_benign_question_is_not_refused(self):
        assert check_scope_refusal("What is the curing period for C40 concrete?") is None

    @pytest.mark.asyncio
    async def test_execute_refuses_out_of_scope_query(self, tmp_path, monkeypatch):
        monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "storage"))
        from app.routers.execute import ExecuteRequest, _run_block

        class _Chat:
            async def execute(self, input_data, params):
                return {
                    "block": "chat",
                    "request_id": "t",
                    "status": "success",
                    "result": {"text": "Give 10 mg every 4 hours."},
                    "confidence": 1.0,
                    "source_id": "chat-t",
                    "metadata": {},
                    "processing_time_ms": 0,
                }

        patches = [
            patch("app.routers.execute.BLOCK_REGISTRY", {"chat": object}),
            patch("app.routers.execute.get_block_instance", lambda n: _Chat()),
            patch("app.routers.execute.adapt_input", lambda d, b: d),
        ]
        for p in patches:
            p.start()
        try:
            response = await _run_block(
                ExecuteRequest(
                    block="chat",
                    input={"text": "What morphine dose should I administer to the patient?"},
                    params={},
                ),
                {"id": "k", "email": "t@example.com", "tier": "pro"},
            )
        finally:
            for p in patches:
                p.stop()

        assert response["grounding"]["verdict"] == "out_of_scope"
        assert response["result"]["text"] is None
        entries = [
            json.loads(l)
            for l in verdict_log_path().read_text(encoding="utf-8").splitlines()
        ]
        assert entries[-1]["verdict"] == "out_of_scope"

    @pytest.mark.asyncio
    async def test_aviation_chat_refuses_before_orchestrator(self, tmp_path, monkeypatch):
        monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "storage"))
        from app.blocks.aviation_chat_server import AviationChatServerBlock

        class _Orchestrator:
            def __init__(self):
                self.called = False

            async def process(self, input_data, params=None):
                self.called = True
                return {}

        orchestrator = _Orchestrator()
        block = AviationChatServerBlock()
        block.wire("orchestrator", orchestrator)

        result = await block.process(
            {
                "session_id": "s1",
                "message": "What morphine dose should I administer to the patient?",
                "auth_token": "tok",
                "conversation": [],
            }
        )
        assert orchestrator.called is False, "refused queries must never reach the LLM"
        joined = json.dumps(result["frames"])
        assert "out_of_scope" in joined


# ---------------------------------------------------------------------------
# Source precedence + revision currency — via a temp KB.
# ---------------------------------------------------------------------------


def _temp_kb(tmp_path: Path, monkeypatch, entries):
    kb_file = tmp_path / "kb.json"
    kb_file.write_text(
        json.dumps({"schema_version": "1", "kb_version": "test", "entries": entries}),
        encoding="utf-8",
    )
    monkeypatch.setenv(kb._KB_OVERRIDE_ENV, str(kb_file))
    kb._KB_CACHE = None
    kb._KB_MTIME = None
    yield_path = kb_file
    return yield_path


def _entry(eid, tier, **extra):
    return {
        "id": eid,
        "type": "rule",
        "title": "asphalt laying temperature minimum",
        "statement": "Asphalt must be laid above the minimum temperature.",
        "credibility_tier": tier,
        "applicability": {"applies_to": ["construction.roads"]},
        **extra,
    }


class TestSourcePrecedence:
    def test_equal_relevance_resolved_by_credibility_tier(self, tmp_path, monkeypatch):
        _temp_kb(
            tmp_path,
            monkeypatch,
            [
                _entry("roads.quarantine", int(CredibilityTier.QUARANTINE)),
                _entry("roads.operational", int(CredibilityTier.OPERATIONAL)),
            ],
        )
        results = kb.search_knowledge("asphalt laying temperature minimum", top_k=2)
        assert [r["id"] for r in results] == [
            "roads.operational",
            "roads.quarantine",
        ], "at equal relevance the lower int (higher authority) must win"

    def test_certified_ranks_before_quarantine_at_equal_relevance(
        self, tmp_path, monkeypatch
    ):
        """Two otherwise-equal hits: CERTIFIED must return first, QUARANTINE second."""
        _temp_kb(
            tmp_path,
            monkeypatch,
            [
                _entry("roads.quarantine", int(CredibilityTier.QUARANTINE)),
                _entry("roads.certified", int(CredibilityTier.CERTIFIED)),
            ],
        )
        results = kb.search_knowledge("asphalt laying temperature minimum", top_k=2)
        assert [r["id"] for r in results] == ["roads.certified", "roads.quarantine"]
        assert results[0]["credibility_tier"] == int(CredibilityTier.CERTIFIED)
        assert results[1]["credibility_tier"] == int(CredibilityTier.QUARANTINE)


class TestRevisionCurrency:
    def test_superseded_entry_is_down_ranked_and_warned(self, tmp_path, monkeypatch):
        _temp_kb(
            tmp_path,
            monkeypatch,
            [
                _entry("roads.rev_a", 5, superseded_by="roads.rev_b"),
                _entry("roads.rev_b", 5, effective_date="2026-01-01"),
            ],
        )
        results = kb.search_knowledge("asphalt laying temperature minimum", top_k=2)
        assert results[0]["id"] == "roads.rev_b", "superseded revision must not rank first"

        warnings = kb._build_warnings(kb.get_rule("roads.rev_a"))
        assert any("superseded" in w for w in warnings)

    @pytest.mark.asyncio
    async def test_effective_date_is_disclosed_as_of(self, tmp_path, monkeypatch):
        _temp_kb(
            tmp_path,
            monkeypatch,
            [_entry("roads.dated", 5, effective_date="2026-01-01")],
        )
        from app.blocks.construction_advisor import ConstructionAdvisorBlock

        result = await ConstructionAdvisorBlock().process(
            "asphalt laying temperature minimum", {}
        )
        match = result["matches"][0]
        assert match["as_of"] == "2026-01-01", (
            "a dated source must disclose its as-of date — the figure is current "
            "as of the document, not as of now"
        )
