"""Conflict detection + provenance recording (kernel components).

- ConflictDetector: two artifacts that claim the same id with different
  content (same domain, different definitions) produce a named conflict
  record; the kernel refuses to silently resolve it.
- ProvenanceRecorder: append-only, digest-chained records for every
  significant kernel operation. Tampering with an earlier record breaks
  the chain and is detected on verify().
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, List, Optional

from app.reasoning_kernel import ReasoningResult, ReasoningStatus


class ConflictDetector:
    def __init__(self) -> None:
        self._registered: Dict[str, Dict[str, Any]] = {}
        self._conflicts: List[Dict[str, Any]] = []

    def register(self, artifact_id: str, version: str, content: Dict[str, Any], *, domain: str) -> Optional[Dict[str, Any]]:
        """Register an artifact definition. Returns a conflict record when
        a DIFFERENT definition already holds the same id in the domain."""
        key = f"{domain}:{artifact_id}"
        existing = self._registered.get(key)
        if existing and existing["content"] != content:
            record = {
                "conflict_id": f"conflict:{key}:{existing['version']}-vs-{version}",
                "domain": domain,
                "artifact_id": artifact_id,
                "versions": [existing["version"], version],
            }
            self._conflicts.append(record)
            return record
        self._registered[key] = {"version": version, "content": content, "domain": domain}
        return None

    def conflicts(self) -> List[Dict[str, Any]]:
        """Every conflict registered so far, oldest first."""
        return list(self._conflicts)


class ProvenanceRecorder:
    """Digest-chained, append-only record of kernel operations."""

    def __init__(self) -> None:
        self._records: List[Dict[str, Any]] = []
        self._head = "0" * 64

    def record(self, event: str, payload: Dict[str, Any], *, domain: str = "") -> Dict[str, Any]:
        digest = hashlib.sha256(
            json.dumps({"event": event, "payload": payload}, sort_keys=True, default=str).encode()
        ).hexdigest()
        record = {
            "seq": len(self._records),
            "event": event,
            "domain": domain,
            "payload": payload,
            "digest": digest,
            "prev": self._head,
            "at": time.time(),
        }
        self._head = hashlib.sha256((self._head + digest).encode()).hexdigest()
        self._records.append(record)
        return record

    def head(self) -> str:
        return self._head

    def verify(self) -> List[int]:
        """Return sequence numbers whose content digest or chain link is broken."""
        broken: List[int] = []
        head = "0" * 64
        for record in self._records:
            recomputed = hashlib.sha256(
                json.dumps(
                    {"event": record["event"], "payload": record["payload"]},
                    sort_keys=True,
                    default=str,
                ).encode()
            ).hexdigest()
            if recomputed != record["digest"]:
                broken.append(record["seq"])
            if record["prev"] != head:
                broken.append(record["seq"])
            head = hashlib.sha256((head + record["digest"]).encode()).hexdigest()
        if self._records and head != self._head:
            broken.append(self._records[-1]["seq"])
        return sorted(set(broken))

    def all(self) -> List[Dict[str, Any]]:
        return [dict(r) for r in self._records]
