"""validate_transition must be reachable as a live block action."""

import pytest

from app.blocks.construction_advisor import ConstructionAdvisorBlock


@pytest.mark.asyncio
async def test_validate_transition_action_allows_legal_transition():
    block = ConstructionAdvisorBlock()
    result = await block.execute(
        {
            "rule_id": "procurement.tender_lifecycle",
            "state": "draft",
            "event": {"to": "issued"},
            "context": {},
        },
        {"action": "validate_transition"},
    )
    body = result["result"]
    assert body["status"] == "success", body
    assert "allowed" in body


@pytest.mark.asyncio
async def test_validate_transition_action_rejects_unknown_rule():
    block = ConstructionAdvisorBlock()
    result = await block.execute(
        {
            "rule_id": "no.such.rule",
            "state": "draft",
            "event": {"to": "issued"},
            "context": {},
        },
        {"action": "validate_transition"},
    )
    body = result["result"]
    assert body["status"] == "error"


@pytest.mark.asyncio
async def test_guarded_transition_denied_when_context_fails_guard():
    """The guard must actually gate: same edge, failing context → not allowed."""
    block = ConstructionAdvisorBlock()
    result = await block.execute(
        {
            "rule_id": "procurement.tender_lifecycle",
            "state": "JOB_REQUISITION",
            "event": {"to": "SOLE_SOURCE_REVIEW"},
            "context": {"sole_source": False},
        },
        {"action": "validate_transition"},
    )
    assert result["result"]["allowed"] is False


@pytest.mark.asyncio
async def test_guarded_transition_allowed_when_context_passes_guard():
    block = ConstructionAdvisorBlock()
    result = await block.execute(
        {
            "rule_id": "procurement.tender_lifecycle",
            "state": "JOB_REQUISITION",
            "event": {"to": "SOLE_SOURCE_REVIEW"},
            "context": {"sole_source": True},
        },
        {"action": "validate_transition"},
    )
    assert result["result"]["allowed"] is True


def test_guard_eval_refuses_function_calls():
    """The AST allowlist must reject anything beyond context access/comparison."""
    from app.blocks import _knowledge as kb

    with pytest.raises(kb.GuardEvalError):
        kb._safe_guard_eval("__import__('os').system('id')", {})
    with pytest.raises(kb.GuardEvalError):
        kb._safe_guard_eval("context.f()", {"f": lambda: True})
