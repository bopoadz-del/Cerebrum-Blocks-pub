"""Tests for the neutral block-runner sub-kit."""

import pytest

from block_store.kits.universal_kernel.wave1.audit_evidence import reset_audit_log
from block_store.kits.universal_kernel.wave1.audit_evidence.code import (
    _default_log as audit_log,
)
from block_store.kits.universal_kernel.wave3.structured_outcomes import OutcomeStatus
from block_store.kits.universal_kernel.wave4.block_runner import (
    BlockEnvelope,
    BlockRunner,
    RestrictedRunner,
)


@pytest.fixture(autouse=True)
def _clean_audit_log():
    reset_audit_log()
    yield
    reset_audit_log()


def _echo_handler(arguments):
    return {"echoed": arguments.get("message")}


def _pure_add(arguments):
    return {"sum": arguments["a"] + arguments["b"]}


def test_happy_path():
    runner = BlockRunner(
        allowlist=["echo"],
        registry={"echo": _echo_handler},
    )
    envelope = BlockEnvelope(
        command="echo",
        arguments={"message": "hello"},
        principal={"id": "user-1"},
        scope={"tenant_id": "tenant-1"},
    )
    outcome = runner.run(envelope)
    assert outcome.status == OutcomeStatus.success
    assert outcome.data["echoed"] == "hello"
    assert outcome.honesty == "direct"


def test_denies_unlisted_command():
    runner = BlockRunner(
        allowlist=["echo"],
        registry={"echo": _echo_handler},
    )
    envelope = BlockEnvelope(
        command="delete",
        arguments={},
        principal={"id": "user-1"},
        scope={"tenant_id": "tenant-1"},
    )
    outcome = runner.run(envelope)
    assert outcome.status == OutcomeStatus.failure
    assert outcome.data["error_code"] == "command_not_allowed"


def test_denies_unsafe_arguments():
    runner = BlockRunner(
        allowlist=["echo"],
        registry={"echo": _echo_handler},
    )
    envelope = BlockEnvelope(
        command="echo",
        arguments={"message": "__import__('os').system('rm -rf /')"},
        principal={"id": "user-1"},
        scope={"tenant_id": "tenant-1"},
    )
    outcome = runner.run(envelope)
    assert outcome.status == OutcomeStatus.failure
    assert outcome.data["error_code"] == "unsafe_arguments"


def test_handler_error_returns_failure():
    def _boom(arguments):
        raise RuntimeError("secret details")

    runner = BlockRunner(
        allowlist=["boom"],
        registry={"boom": _boom},
    )
    envelope = BlockEnvelope(
        command="boom",
        arguments={},
        principal={"id": "user-1"},
        scope={"tenant_id": "tenant-1"},
    )
    outcome = runner.run(envelope)
    assert outcome.status == OutcomeStatus.failure
    assert outcome.data["error_code"] == "handler_exception"
    assert "secret details" not in outcome.data["error_message"]


def test_audit_evidence_recorded():
    runner = BlockRunner(
        allowlist=["echo"],
        registry={"echo": _echo_handler},
    )
    envelope = BlockEnvelope(
        command="echo",
        arguments={"message": "hello"},
        principal={"id": "user-1"},
        scope={"tenant_id": "tenant-1"},
    )
    before = len(audit_log.records())
    runner.run(envelope)
    records = audit_log.records()
    assert len(records) == before + 1
    assert records[-1]["event_type"] == "block_executed"


def test_schema_validation():
    runner = BlockRunner(
        allowlist=["add"],
        registry={"add": _pure_add},
        schemas={"add": {"a": {"type": "integer"}, "b": {"type": "integer"}}},
    )
    envelope = BlockEnvelope(
        command="add",
        arguments={"a": 1, "b": "two"},
        principal={"id": "user-1"},
        scope={"tenant_id": "tenant-1"},
    )
    outcome = runner.run(envelope)
    assert outcome.status == OutcomeStatus.failure
    assert outcome.data["error_code"] == "schema_validation_error"


def test_restricted_runner_accepts_pure_function():
    runner = RestrictedRunner(
        allowlist=["add"],
        registry={"add": _pure_add},
    )
    envelope = BlockEnvelope(
        command="add",
        arguments={"a": 2, "b": 3},
        principal={"id": "user-1"},
        scope={"tenant_id": "tenant-1"},
    )
    outcome = runner.run(envelope)
    assert outcome.status == OutcomeStatus.success
    assert outcome.data["sum"] == 5


def test_restricted_runner_rejects_file_access():
    def _file_reader(arguments):
        with open(arguments["path"]) as f:  # noqa: SIM115 - deliberate for test
            return {"content": f.read()}

    runner = RestrictedRunner(
        allowlist=["read"],
        registry={"read": _file_reader},
    )
    envelope = BlockEnvelope(
        command="read",
        arguments={"path": "/etc/passwd"},
        principal={"id": "user-1"},
        scope={"tenant_id": "tenant-1"},
    )
    outcome = runner.run(envelope)
    assert outcome.status == OutcomeStatus.failure
    assert outcome.data["error_code"] == "handler_security_error"
