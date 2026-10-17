"""Persistence for the neutral platform.

NEUTRAL_DB_URL is required (no default): sqlite:///<path> for the zero-setup
demo, or PostgreSQL, e.g. postgresql+psycopg2://neutral@localhost:5432/neutral
with the password in PGPASSWORD (never in the URL). The same E2E suite
runs against both — CI exercises PostgreSQL with a service container.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class InspectionRow(Base):
    __tablename__ = "inspections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    equipment_id = Column(String(64), nullable=False)
    condition = Column(String(32), nullable=False)
    likelihood = Column(Integer, nullable=False)
    consequence = Column(Integer, nullable=False)
    hours_since_service = Column(Integer, nullable=False)
    service_interval_hours = Column(Integer, nullable=False)
    equipment_class = Column(String(32), nullable=False)
    risk_score = Column(Integer, nullable=True)
    risk_band = Column(String(16), nullable=True)
    actions = Column(JSON, nullable=True)
    explanation = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class WorkOrderRow(Base):
    __tablename__ = "work_orders"

    id = Column(String(64), primary_key=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    inspection_id = Column(Integer, nullable=False)
    requester_id = Column(String(64), nullable=False)
    state = Column(String(32), nullable=False)
    priority = Column(String(16), nullable=False)
    history = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class AuditRow(Base):
    __tablename__ = "audit_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    entity = Column(String(64), nullable=False)
    event = Column(String(64), nullable=False)
    payload_json = Column(Text, nullable=False)
    prev_hash = Column(String(64), nullable=False)
    record_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


_engine = None
_Session = None


def get_engine():
    global _engine, _Session
    if _engine is None:
        url = os.environ.get("NEUTRAL_DB_URL", "").strip()
        if not url:
            raise RuntimeError(
                "NEUTRAL_DB_URL is not set (no default): sqlite:///<path> for the demo, "
                "or a PostgreSQL URL with the password in PGPASSWORD"
            )
        kwargs: Dict[str, Any] = {"future": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        _engine = create_engine(url, **kwargs)
        _Session = sessionmaker(bind=_engine)
    return _engine


def get_session():
    get_engine()
    return _Session()


def init_db() -> None:
    Base.metadata.create_all(get_engine())


def reset_db_engine() -> None:
    """Tests: drop the cached engine so a new env var takes effect."""
    global _engine, _Session
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _Session = None


def record_audit(session, tenant_id: str, entity: str, event: str, payload: Dict[str, Any]) -> str:
    """Append an audit event with a chained hash (prev_hash -> record_hash)."""
    prev = session.query(AuditRow).filter(AuditRow.tenant_id == tenant_id).order_by(AuditRow.id.desc()).first()
    prev_hash = prev.record_hash if prev else ("0" * 64)
    canonical = json.dumps(
        {"tenant_id": tenant_id, "entity": entity, "event": event, "payload": payload},
        sort_keys=True,
        default=str,
    )
    record_hash = hashlib.sha256((prev_hash + canonical).encode()).hexdigest()
    row = AuditRow(
        tenant_id=tenant_id,
        entity=entity,
        event=event,
        payload_json=canonical,
        prev_hash=prev_hash,
        record_hash=record_hash,
    )
    session.add(row)
    session.commit()
    return record_hash


def verify_chain(session, tenant_id: str) -> Dict[str, Any]:
    """Recompute the hash chain; any drift breaks verification."""
    rows = session.query(AuditRow).filter(AuditRow.tenant_id == tenant_id).order_by(AuditRow.id).all()
    verified = True
    prev = "0" * 64
    for row in rows:
        expected = hashlib.sha256((prev + row.payload_json).encode()).hexdigest()
        if row.record_hash != expected or row.prev_hash != prev:
            verified = False
        prev = row.record_hash
    return {"events": len(rows), "verified": verified, "head": rows[-1].record_hash if rows else None}
