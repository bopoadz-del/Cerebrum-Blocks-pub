"""Neutral proof platform API (FastAPI).

The full mission loop: login -> tenant-scoped inspection -> deterministic
condition rules -> risk score -> recommended maintenance action ->
required approval level -> correct-role approval -> one approved workflow
transition -> one unsupported transition refused -> evidence-grounded
explanation -> XLSX/PDF output -> verified audit chain.

Every domain decision comes from the kernel engines; this file only
carries requests to them and persists results.
"""

from __future__ import annotations

import io
import json
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import Response
from openpyxl import Workbook
from pydantic import BaseModel
from fpdf import FPDF

from . import db
from .auth import AuthError, issue_token, principal_from_header
from .platform import close_payload, get_platform

app = FastAPI(title="Cerebrum Neutral Proof Platform", version="1.0.0")


class LoginRequest(BaseModel):
    user_id: str


class InspectionRequest(BaseModel):
    equipment_id: str
    condition: str
    likelihood: int
    consequence: int
    hours_since_service: int
    service_interval_hours: int
    equipment_class: str


class WorkOrderRequest(BaseModel):
    inspection_id: int


class TransitionRequest(BaseModel):
    to_state: str
    evidence: Dict[str, Any] = {}
    approval_token: Optional[str] = None


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


def _principal(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    try:
        return principal_from_header(authorization)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from None


def _result_body(result: Any) -> Dict[str, Any]:
    return {
        "status": getattr(result, "status", None).value
        if getattr(result, "status", None)
        else "success",
        "explanation": getattr(result, "explanation", ""),
        "workflow": getattr(result, "workflow", None),
        "approval": getattr(result, "approval", None),
        "missing_inputs": getattr(result, "missing_inputs", []),
        "rules_applied": getattr(result, "rules_applied", []),
        "formulas_applied": getattr(result, "formulas_applied", []),
        "recommended_actions": getattr(result, "recommended_actions", []),
        "prohibited_actions": getattr(result, "prohibited_actions", []),
        "evidence": getattr(result, "evidence", []),
        "input_digest": getattr(result, "input_digest", ""),
        "output_digest": getattr(result, "output_digest", ""),
    }


@app.post("/login")
def login(body: LoginRequest):
    try:
        return {"token": issue_token(body.user_id)}
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from None


@app.post("/inspections")
def submit_inspection(body: InspectionRequest, principal: Dict[str, Any] = Depends(_principal)):
    platform = get_platform()
    inspection, results = platform.run_inspection(body.model_dump())
    session = db.get_session()
    try:
        if inspection is None:
            # A refusal rule fired — the inspection is refused by name.
            refusal = [r for r in results if getattr(r, "prohibited_actions", None)]
            detail = _result_body(refusal[0]) if refusal else {"status": "validation_error"}
            db.record_audit(session, principal["tenant_id"], "inspection", "refused", detail)
            raise HTTPException(status_code=422, detail=detail)
        row = db.InspectionRow(
            tenant_id=principal["tenant_id"],
            **{k: v for k, v in inspection.items() if k in db.InspectionRow.__table__.columns},
        )
        session.add(row)
        session.commit()
        inspection_id = row.id
        db.record_audit(
            session,
            principal["tenant_id"],
            f"inspection:{inspection_id}",
            "submitted",
            {"inspection": inspection, "results": [_result_body(r) for r in results]},
        )
        return {
            "inspection_id": inspection_id,
            "inspection": inspection,
            "results": [_result_body(r) for r in results],
        }
    finally:
        session.close()


@app.get("/inspections/{inspection_id}")
def get_inspection(inspection_id: int, principal: Dict[str, Any] = Depends(_principal)):
    session = db.get_session()
    try:
        row = session.get(db.InspectionRow, inspection_id)
        if row is None or row.tenant_id != principal["tenant_id"]:
            raise HTTPException(status_code=404, detail="inspection not found")
        return {
            "inspection_id": row.id,
            "equipment_id": row.equipment_id,
            "condition": row.condition,
            "risk_score": row.risk_score,
            "risk_band": row.risk_band,
            "actions": row.actions,
            "explanation": row.explanation,
            "tenant_id": row.tenant_id,
        }
    finally:
        session.close()


@app.post("/work_orders")
def create_work_order(body: WorkOrderRequest, principal: Dict[str, Any] = Depends(_principal)):
    session = db.get_session()
    try:
        inspection = session.get(db.InspectionRow, body.inspection_id)
        if inspection is None or inspection.tenant_id != principal["tenant_id"]:
            raise HTTPException(status_code=404, detail="inspection not found")
        platform = get_platform()
        work_order_id = f"wo-{inspection.id}"
        result = platform.create_work_order(
            work_order_id,
            {
                "risk_score": inspection.risk_score,
                "risk_band": inspection.risk_band,
                "equipment_id": inspection.equipment_id,
            },
        )
        if result.status.value != "success":
            raise HTTPException(status_code=409, detail=_result_body(result))
        row = db.WorkOrderRow(
            id=work_order_id,
            tenant_id=principal["tenant_id"],
            inspection_id=inspection.id,
            requester_id=principal["sub"],
            state="draft",
            priority="immediate" if inspection.risk_band == "critical" else "routine",
            history=[{"from": None, "to": "draft"}],
        )
        session.add(row)
        session.commit()
        db.record_audit(session, principal["tenant_id"], f"work_order:{work_order_id}", "created", {"state": "draft"})
        return {"work_order_id": work_order_id, "state": "draft"}
    finally:
        session.close()


def _load_work_order(session, work_order_id: str, principal: Dict[str, Any]) -> db.WorkOrderRow:
    row = session.get(db.WorkOrderRow, work_order_id)
    if row is None or row.tenant_id != principal["tenant_id"]:
        raise HTTPException(status_code=404, detail="work order not found")
    return row


@app.get("/work_orders/{work_order_id}")
def get_work_order(work_order_id: str, principal: Dict[str, Any] = Depends(_principal)):
    session = db.get_session()
    try:
        row = _load_work_order(session, work_order_id, principal)
        return {
            "work_order_id": row.id,
            "state": row.state,
            "priority": row.priority,
            "inspection_id": row.inspection_id,
            "history": row.history,
            "tenant_id": row.tenant_id,
        }
    finally:
        session.close()


@app.post("/work_orders/{work_order_id}/transition")
def transition_work_order(
    work_order_id: str,
    body: TransitionRequest,
    principal: Dict[str, Any] = Depends(_principal),
):
    session = db.get_session()
    try:
        row = _load_work_order(session, work_order_id, principal)
        platform = get_platform()
        payload = close_payload(work_order_id) if body.to_state == "closed" else {}
        result = platform.transition(
            work_order_id,
            body.to_state,
            actor=principal["role"],
            evidence=body.evidence or None,
            approval_token=body.approval_token,
            requester_id=row.requester_id,
            payload=payload,
        )
        if result.status.value == "success":
            row.state = body.to_state
            row.history = (row.history or []) + [{"from": result.workflow.get("previous"), "to": body.to_state, "by": principal["role"]}]
            session.commit()
            db.record_audit(
                session,
                principal["tenant_id"],
                f"work_order:{work_order_id}",
                f"transition_to_{body.to_state}",
                {"result": _result_body(result)},
            )
        body_result = _result_body(result)
        if body.approval_token and result.status.value == "approval_required":
            body_result["approval_refusals"] = [
                entry
                for entry in platform.audit_log()
                if entry.get("event") == "refused"
            ]
        return body_result
    finally:
        session.close()


@app.post("/work_orders/{work_order_id}/close-approval")
def close_approval(
    work_order_id: str,
    principal: Dict[str, Any] = Depends(_principal),
    ttl_seconds: Optional[int] = Query(default=None),
):
    session = db.get_session()
    try:
        row = _load_work_order(session, work_order_id, principal)
        platform = get_platform()
        payload = close_payload(work_order_id)
        requirement = platform.approval_requirement(
            payload, {"role": principal["role"], "id": principal["sub"]}
        )
        from app.reasoning_kernel.approvals import ApprovalRefused

        try:
            token = platform.issue_approval(
                approver={
                    "id": principal["sub"],
                    "role": principal["role"],
                    "requester_id": row.requester_id,
                },
                payload=payload,
                ttl_seconds=ttl_seconds,
            )
        except ApprovalRefused as exc:
            db.record_audit(session, principal["tenant_id"], f"work_order:{work_order_id}", "approval_refused", {"reason": str(exc)})
            raise HTTPException(status_code=403, detail={"status": "permission_denied", "explanation": str(exc)}) from None
        db.record_audit(session, principal["tenant_id"], f"work_order:{work_order_id}", "approval_issued", {"requirement": _result_body(requirement)})
        return {"token": token, "requirement": _result_body(requirement)}
    finally:
        session.close()


def _report_bytes(work_order_id: str, principal: Dict[str, Any]) -> tuple:
    session = db.get_session()
    try:
        row = _load_work_order(session, work_order_id, principal)
        inspection = session.get(db.InspectionRow, row.inspection_id)
        chain = db.verify_chain(session, principal["tenant_id"])
        title = f"Cerebrum Neutral Platform — Work Order {work_order_id}"
        facts = [
            ("Equipment", inspection.equipment_id),
            ("Class", inspection.equipment_class),
            ("Condition", inspection.condition),
            ("Risk score", str(inspection.risk_score)),
            ("Risk band", inspection.risk_band or "-"),
            ("State", row.state),
            ("Priority", row.priority),
            ("Tenant", principal["tenant_id"]),
            ("Explanation", (inspection.explanation or "").replace("\n", " | ")),
            ("Audit events", str(chain["events"])),
            ("Audit verified", "YES" if chain["verified"] else "NO"),
            ("Audit head", chain["head"] or "-"),
        ]
        return facts, title
    finally:
        session.close()


@app.get("/work_orders/{work_order_id}/report.xlsx")
def report_xlsx(work_order_id: str, principal: Dict[str, Any] = Depends(_principal)):
    facts, title = _report_bytes(work_order_id, principal)
    wb = Workbook()
    ws = wb.active
    ws.title = "work_order"
    ws.append([title])
    for key, value in facts:
        ws.append([key, value])
    buf = io.BytesIO()
    wb.save(buf)
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{work_order_id}.xlsx"'},
    )


@app.get("/work_orders/{work_order_id}/report.pdf")
def report_pdf(work_order_id: str, principal: Dict[str, Any] = Depends(_principal)):
    facts, title = _report_bytes(work_order_id, principal)

    def _safe(value: Any) -> str:
        # helvetica core font: latin-1 only — replace anything exotic
        return str(value).encode("latin-1", "replace").decode("latin-1")

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", "B", 14)
    pdf.cell(190, 10, _safe(title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", "", 10)
    for key, value in facts:
        pdf.set_font("helvetica", "B", 10)
        pdf.cell(45, 7, _safe(key), border=1)
        pdf.set_font("helvetica", "", 10)
        pdf.multi_cell(145, 7, _safe(value), border=1)
    return Response(
        content=bytes(pdf.output()),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{work_order_id}.pdf"'},
    )


@app.get("/work_orders/{work_order_id}/audit")
def work_order_audit(work_order_id: str, principal: Dict[str, Any] = Depends(_principal)):
    session = db.get_session()
    try:
        _load_work_order(session, work_order_id, principal)
        events = (
            session.query(db.AuditRow)
            .filter(db.AuditRow.tenant_id == principal["tenant_id"])
            .order_by(db.AuditRow.id)
            .all()
        )
        return {
            "work_order_id": work_order_id,
            "chain": db.verify_chain(session, principal["tenant_id"]),
            "events": [
                {"id": e.id, "entity": e.entity, "event": e.event, "record_hash": e.record_hash, "prev_hash": e.prev_hash}
                for e in events
            ],
        }
    finally:
        session.close()


@app.get("/health")
def health():
    return {"status": "ok"}
