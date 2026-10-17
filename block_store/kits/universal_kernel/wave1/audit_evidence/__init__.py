"""Audit evidence sub-kit: append-only hash-chained audit records."""

from .code import (
    AuditIntegrityError,
    AuditLog,
    ZERO_HASH,
    record,
    reset_audit_log,
    verify_chain,
)

__all__ = [
    "AuditIntegrityError",
    "AuditLog",
    "ZERO_HASH",
    "record",
    "reset_audit_log",
    "verify_chain",
]
