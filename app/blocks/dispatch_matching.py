"""Dispatch Matching - deterministic job-to-worker matching and assignment.

The delivery/rideshare core: register workers and jobs, score every active
worker for a job (skills, distance, load, reputation), assign within
capacity, let workers accept/reject with a timeout window, and release on
cancel. Pure decision block: no network, no filesystem, no wall clock -
timeout accounting uses caller-supplied sequence numbers so behavior is
fully reproducible.

Every score is decomposed and reported; assignments are exclusive (a job
has at most one assigned worker) and fail-closed on unknown ids, inactive
workers, and capacity violations.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.universal_base import UniversalBlock
from app.core.http_errors import error_kind

DEFAULT_WEIGHTS: Dict[str, float] = {
    "skills": 0.40,
    "distance": 0.30,
    "load": 0.15,
    "reputation": 0.15,
}


class DispatchMatchingBlock(UniversalBlock):
    """Deterministic dispatch: scoring, assignment, accept/reject lifecycle."""

    name = "dispatch_matching"
    version = "1.0.0"
    description = (
        "Deterministic job-to-worker dispatch: skill/distance/load/reputation "
        "scoring with component decomposition, capacity-guarded exclusive "
        "assignment, accept/reject lifecycle with sequence-based timeouts, "
        "and release on cancel."
    )
    layer = 3
    tags = ["domain", "marketplace", "dispatch", "matching", "deterministic"]
    requires: List[str] = []
    author = "Cerebrum Team"
    default_config: Dict[str, Any] = {
        "score_weights": dict(DEFAULT_WEIGHTS),
        "max_distance_km": 30.0,
        "accept_timeout_steps": 50,
    }
    ui_schema = {
        "input": {"type": "json"},
        "output": {"type": "json"},
        "params": [],
        "quick_actions": [],
    }

    def __init__(self, hal_block=None, config: Dict = None):
        super().__init__(hal_block, config)
        self.workers: Dict[str, Dict[str, Any]] = {}
        self.jobs: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------ api
    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        data = input_data if isinstance(input_data, dict) else {}
        merged = {**params, **data}
        operation = merged.get("operation") or merged.get("action") or "match"

        try:
            if operation == "register_worker":
                return self._register_worker(merged)
            if operation == "register_job":
                return self._register_job(merged)
            if operation == "match":
                return self._match(merged)
            if operation == "assign":
                return self._assign(merged)
            if operation == "accept":
                return self._respond(merged, "accepted")
            if operation == "reject":
                return self._respond(merged, "rejected")
            if operation == "release":
                return self._release(merged)
            if operation == "status":
                return self._status(merged)
        except ValueError as exc:
            return {"status": "error", "error": str(exc), "error_kind": error_kind(exc), "operation": operation}

        return {
            "status": "error",
            "error": f"Unknown operation: {operation}",
            "available_operations": [
                "register_worker", "register_job", "match", "assign",
                "accept", "reject", "release", "status",
            ],
        }

    # -------------------------------------------------------------- helpers
    def _require(self, data: Dict[str, Any], keys: List[str]) -> Optional[str]:
        for key in keys:
            value = data.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                return key
        return None

    def _worker_load(self, worker: Dict[str, Any]) -> float:
        assigned = sum(
            1 for job in self.jobs.values()
            if job.get("worker_id") == worker["worker_id"]
            and job.get("state") in ("assigned", "accepted", "in_progress")
        )
        return min(1.0, assigned / max(1, worker.get("capacity", 1)))

    def _score_worker(self, worker: Dict[str, Any], job: Dict[str, Any]) -> Dict[str, Any]:
        weights = self.config.get("score_weights") or DEFAULT_WEIGHTS
        skills = set(job.get("required_skills") or [])
        have = set(worker.get("skills") or [])
        skill_score = 1.0 if not skills else (len(skills & have) / len(skills)) if skills else 1.0
        distance = float(job.get("distance_km") or 0.0)
        max_distance = float(self.config.get("max_distance_km") or 30.0)
        distance_score = max(0.0, 1.0 - distance / max_distance) if max_distance > 0 else 0.0
        load = self._worker_load(worker)
        load_score = 1.0 - load
        reputation = min(max(float(worker.get("reputation", 0.5)), 0.0), 1.0)
        total = (
            weights["skills"] * skill_score
            + weights["distance"] * distance_score
            + weights["load"] * load_score
            + weights["reputation"] * reputation
        )
        return {
            "score": round(total, 4),
            "components": {
                "skills": round(skill_score, 4),
                "distance": round(distance_score, 4),
                "load": round(load_score, 4),
                "reputation": round(reputation, 4),
            },
        }

    # ----------------------------------------------------------- operations
    def _register_worker(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["worker_id"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        worker_id = data["worker_id"]
        existing = self.workers.get(worker_id)
        if existing is not None:
            return {**existing["public"], "idempotent": True}
        record = {
            "worker_id": worker_id,
            "skills": list(data.get("skills") or []),
            "location": data.get("location") or {},
            "capacity": max(1, int(data.get("capacity") or 1)),
            "reputation": float(data.get("reputation", 0.5)),
            "active": bool(data.get("active", True)),
        }
        public = {
            "status": "success",
            "operation": "register_worker",
            "worker_id": worker_id,
            "skills": record["skills"],
            "capacity": record["capacity"],
        }
        record["public"] = public
        self.workers[worker_id] = record
        return public

    def _register_job(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["job_id"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        job_id = data["job_id"]
        existing = self.jobs.get(job_id)
        if existing is not None:
            return {**existing["public"], "idempotent": True}
        record = {
            "job_id": job_id,
            "required_skills": list(data.get("required_skills") or []),
            "location": data.get("location") or {},
            "distance_km": float(data.get("distance_km") or 0.0),
            "state": "open",
            "worker_id": None,
        }
        public = {
            "status": "success",
            "operation": "register_job",
            "job_id": job_id,
            "state": "open",
        }
        record["public"] = public
        self.jobs[job_id] = record
        return public

    def _match(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["job_id"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        job = self.jobs.get(data["job_id"])
        if job is None:
            return {"status": "error", "error": "job_not_found", "job_id": data["job_id"]}
        if job["state"] != "open":
            return {"status": "error", "error": f"job_not_open: {job['state']}"}
        scored: List[Dict[str, Any]] = []
        for worker in self.workers.values():
            if not worker["active"]:
                continue
            if self._worker_load(worker) >= 1.0:
                continue
            scoring = self._score_worker(worker, job)
            scored.append(
                {
                    "worker_id": worker["worker_id"],
                    "skills": worker["skills"],
                    "capacity": worker["capacity"],
                    **scoring,
                }
            )
        scored.sort(key=lambda s: s["score"], reverse=True)
        return {
            "status": "success",
            "operation": "match",
            "job_id": data["job_id"],
            "candidates": scored,
            "count": len(scored),
        }

    def _assign(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["job_id", "worker_id"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        job = self.jobs.get(data["job_id"])
        if job is None:
            return {"status": "error", "error": "job_not_found"}
        worker = self.workers.get(data["worker_id"])
        if worker is None:
            return {"status": "error", "error": "worker_not_found"}
        if not worker["active"]:
            return {"status": "error", "error": "worker_inactive"}
        if self._worker_load(worker) >= 1.0:
            return {"status": "error", "error": "worker_at_capacity"}
        if job["state"] != "open":
            return {"status": "error", "error": f"job_not_open: {job['state']}"}
        job["state"] = "assigned"
        job["worker_id"] = data["worker_id"]
        job["assigned_step"] = data.get("step", 0)
        return {
            "status": "success",
            "operation": "assign",
            "job_id": data["job_id"],
            "worker_id": data["worker_id"],
            "state": "assigned",
        }

    def _respond(self, data: Dict[str, Any], response: str) -> Dict[str, Any]:
        missing = self._require(data, ["job_id", "worker_id"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        job = self.jobs.get(data["job_id"])
        if job is None:
            return {"status": "error", "error": "job_not_found"}
        if job.get("worker_id") != data["worker_id"]:
            return {"status": "error", "error": "job_assigned_to_other_worker"}
        if job["state"] != "assigned":
            return {"status": "error", "error": f"job_not_assigned: {job['state']}"}
        timeout = int(self.config.get("accept_timeout_steps") or 50)
        elapsed = int(data.get("step", job.get("assigned_step", 0))) - int(job.get("assigned_step", 0))
        if elapsed > timeout:
            job["state"] = "open"
            job["worker_id"] = None
            return {
                "status": "error",
                "error": "accept_timeout_expired",
                "job_id": data["job_id"],
                "state": "open",
            }
        job["state"] = response
        return {
            "status": "success",
            "operation": response,
            "job_id": data["job_id"],
            "worker_id": data["worker_id"],
            "state": response,
        }

    def _release(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["job_id"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        job = self.jobs.get(data["job_id"])
        if job is None:
            return {"status": "error", "error": "job_not_found"}
        if job["state"] in ("completed", "cancelled"):
            return {"status": "error", "error": f"job_already_{job['state']}"}
        job["state"] = "open"
        job["worker_id"] = None
        return {
            "status": "success",
            "operation": "release",
            "job_id": data["job_id"],
            "state": "open",
        }

    def _status(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["job_id"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        job = self.jobs.get(data["job_id"])
        if job is None:
            return {"status": "error", "error": "job_not_found"}
        return {
            "status": "success",
            "operation": "status",
            "job_id": data["job_id"],
            "state": job["state"],
            "worker_id": job["worker_id"],
        }
