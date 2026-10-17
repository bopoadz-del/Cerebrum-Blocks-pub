"""Smoke tests for the generic action contract runtime."""
import pytest

from app.blocks.core.action_contract import (
    ActionContext,
    ActionOutcome,
    ActionRegistry,
    ActionSpec,
    ActionStatus,
    execute_action,
)


async def _echo_handler(context: ActionContext, args: dict) -> ActionOutcome:
    return ActionOutcome.success({"echo": args})


@pytest.fixture
def sample_spec() -> ActionSpec:
    return ActionSpec(
        action_id="test.echo",
        domain="test",
        name="echo",
        description="Echo action for tests",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        handler=_echo_handler,
        permissions=[],
    )


@pytest.fixture
def base_context() -> ActionContext:
    return ActionContext(
        user_id="u-1",
        tenant_id="t-1",
        organisation_id="org-1",
        project_id="p-1",
        permissions=["run"],
        allowed_domains=["test"],
    )


async def test_execute_action_success(sample_spec: ActionSpec, base_context: ActionContext) -> None:
    result = await execute_action(sample_spec, base_context, {"hello": "world"})

    assert result.status == ActionStatus.SUCCESS
    assert result.action_id == "test.echo"
    assert result.output["echo"] == {"hello": "world"}


async def test_reserved_keys_stripped_from_args(
    sample_spec: ActionSpec, base_context: ActionContext
) -> None:
    result = await execute_action(
        sample_spec,
        base_context,
        {"hello": "world", "tenant_id": "injected", "permissions": ["admin"]},
    )

    assert result.status == ActionStatus.SUCCESS
    assert "tenant_id" not in result.output["echo"]
    assert "permissions" not in result.output["echo"]
    assert result.output["echo"]["hello"] == "world"


async def test_domain_not_allowed(sample_spec: ActionSpec) -> None:
    context = ActionContext(
        user_id="u-1",
        tenant_id="t-1",
        organisation_id="org-1",
        project_id="p-1",
        permissions=["run"],
        allowed_domains=["other"],
    )
    result = await execute_action(sample_spec, context, {})

    assert result.status == ActionStatus.PERMISSION_DENIED


async def test_missing_permission(sample_spec: ActionSpec, base_context: ActionContext) -> None:
    spec = sample_spec.model_copy(update={"permissions": ["admin"]})
    result = await execute_action(spec, base_context, {})

    assert result.status == ActionStatus.PERMISSION_DENIED


def test_registry_discovers_and_resolves(sample_spec: ActionSpec) -> None:
    registry = ActionRegistry()
    registry.register(sample_spec)

    resolved = registry.resolve("test.echo")
    assert resolved is not None
    assert resolved.action_id == "test.echo"

    missing = registry.resolve("test.missing")
    assert missing is None


def test_registry_rejects_duplicate(sample_spec: ActionSpec) -> None:
    registry = ActionRegistry()
    registry.register(sample_spec)
    with pytest.raises(Exception):
        registry.register(sample_spec)
