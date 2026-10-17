"""Transaction State Machine - deterministic marketplace lifecycle engine.

A typed, fail-closed state machine for gig-economy entities (tasks, orders,
trips, transactions). Vertical presets encode the lifecycle of Airtasker-like
task marketplaces, food delivery orders, rideshare trips, and Sharetribe-like
marketplace transactions. Pure Python: no network, no filesystem, no side
effects. Actor guards, idempotent transition replay, and a full audit trail.

Design contract:
- Every transition is `{state} --event(actor)--> {next_state}`.
- The machine refuses (status=error) on unknown verticals, states, events,
  actors, or transitions; errors always list the legal next events.
- Transition ids make replays idempotent: the same id returns the recorded
  outcome instead of double-applying.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.universal_base import UniversalBlock
from app.core.http_errors import error_kind

# ---- vertical presets -------------------------------------------------------
# Each preset: initial state + {state: {event: next_state}}.
# Events are namespaced with the actor allowed to fire them (see ACTOR_RULES).

TRANSITIONS: Dict[str, Dict[str, Any]] = {
    "task": {
        "initial": "created",
        "states": {
            "created": {"post_offers": "offered", "cancel": "cancelled"},
            "offered": {"accept_offer": "accepted", "cancel": "cancelled"},
            "accepted": {"start": "in_progress", "cancel": "cancelled"},
            "in_progress": {"complete": "completed", "dispute": "disputed", "cancel": "cancelled"},
            "completed": {"review": "reviewed"},
            "disputed": {"resolve_release": "completed", "resolve_refund": "refunded"},
            "cancelled": {},
            "reviewed": {},
            "refunded": {},
        },
    },
    "order": {
        "initial": "created",
        "states": {
            "created": {"accept": "accepted", "cancel": "cancelled"},
            "accepted": {"prepare_done": "ready", "cancel": "cancelled"},
            "ready": {"pickup": "in_delivery"},
            "in_delivery": {"deliver": "delivered", "dispute": "disputed"},
            "delivered": {"review": "reviewed"},
            "disputed": {"resolve_refund": "refunded", "resolve_release": "delivered"},
            "cancelled": {},
            "reviewed": {},
            "refunded": {},
        },
    },
    "trip": {
        "initial": "created",
        "states": {
            "created": {"match": "matched", "cancel": "cancelled"},
            "matched": {"en_route": "driver_en_route", "cancel": "cancelled"},
            "driver_en_route": {"begin": "in_progress"},
            "in_progress": {"complete": "completed", "dispute": "disputed"},
            "completed": {"review": "reviewed"},
            "disputed": {"resolve_refund": "refunded", "resolve_release": "completed"},
            "cancelled": {},
            "reviewed": {},
            "refunded": {},
        },
    },
    "transaction": {
        "initial": "created",
        "states": {
            "created": {"post_offers": "offered", "cancel": "cancelled"},
            "offered": {"accept_offer": "accepted", "cancel": "cancelled"},
            "accepted": {"mark_paid": "paid", "cancel": "cancelled"},
            "paid": {"deliver": "delivered"},
            "delivered": {"complete": "completed", "dispute": "disputed"},
            "completed": {"review": "reviewed"},
            "disputed": {"resolve_refund": "refunded", "resolve_release": "completed"},
            "cancelled": {},
            "reviewed": {},
            "refunded": {},
        },
    },
}

# Which actors may fire which event. Unknown actors are refused.
ACTOR_RULES: Dict[str, List[str]] = {
    "post_offers": ["provider"],
    "accept_offer": ["customer"],
    "accept": ["provider"],
    "cancel": ["customer", "provider", "system"],
    "start": ["provider"],
    "complete": ["provider"],
    "review": ["customer"],
    "dispute": ["customer", "provider"],
    "resolve_release": ["platform"],
    "resolve_refund": ["platform"],
    "prepare_done": ["provider"],
    "pickup": ["provider"],
    "deliver": ["provider"],
    "match": ["system"],
    "en_route": ["provider"],
    "begin": ["provider"],
    "mark_paid": ["system"],
}

TERMINAL_STATES = {"reviewed", "cancelled", "refunded"}

KNOWN_VERTICALS = sorted(TRANSITIONS.keys())
KNOWN_ACTORS = ["customer", "provider", "system", "platform"]


class TransactionStateMachineBlock(UniversalBlock):
    """Deterministic marketplace entity lifecycle machine."""

    name = "transaction_state_machine"
    version = "1.0.0"
    description = (
        "Deterministic fail-closed lifecycle state machine for marketplace "
        "entities (task, order, trip, transaction verticals) with actor "
        "guards, idempotent replay and a per-entity audit trail."
    )
    layer = 3
    tags = ["domain", "marketplace", "state-machine", "deterministic", "core-spine"]
    requires: List[str] = []
    author = "Cerebrum Team"
    default_config: Dict[str, Any] = {}
    ui_schema = {
        "input": {"type": "json"},
        "output": {"type": "json"},
        "params": [],
        "quick_actions": [],
    }

    def __init__(self, hal_block=None, config: Dict = None):
        super().__init__(hal_block, config)
        # entity_id -> {"vertical": str, "state": str, "history": [...]}
        self.entities: Dict[str, Dict[str, Any]] = {}
        # entity_id -> {transition_id: outcome}
        self.replayed: Dict[str, Dict[str, Dict[str, Any]]] = {}

    # ------------------------------------------------------------------ api
    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        data = input_data if isinstance(input_data, dict) else {}
        merged = {**params, **data}
        operation = merged.get("operation") or merged.get("action") or "transition"

        try:
            if operation == "transition":
                return self._transition(merged)
            if operation == "allowed":
                return self._allowed(merged)
            if operation == "machine":
                return self._machine(merged)
            if operation == "replay":
                return self._replay(merged)
        except (ValueError, TypeError) as exc:
            return {"status": "error", "error": str(exc), "error_kind": error_kind(exc), "operation": operation}

        return {
            "status": "error",
            "error": f"Unknown operation: {operation}",
            "available_operations": ["transition", "allowed", "machine", "replay"],
        }

    # -------------------------------------------------------------- helpers
    def _require(self, data: Dict[str, Any], keys: List[str]) -> Optional[str]:
        for key in keys:
            value = data.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                return key
        return None

    def _ensure_entity(self, entity_id: str, vertical: str) -> Dict:
        entity = self.entities.get(entity_id)
        if entity is None:
            preset = TRANSITIONS.get(vertical)
            if preset is None:
                raise ValueError(f"Unknown vertical: {vertical}; known: {KNOWN_VERTICALS}")
            entity = {
                "vertical": vertical,
                "state": preset["initial"],
                "history": [],
            }
            self.entities[entity_id] = entity
            self.replayed.setdefault(entity_id, {})
        if entity["vertical"] != vertical:
            raise ValueError(
                f"Entity {entity_id} is vertical '{entity['vertical']}', "
                f"not '{vertical}'"
            )
        return entity

    def _legal_events(self, entity: Dict) -> List[str]:
        preset = TRANSITIONS[entity["vertical"]]
        return sorted(preset["states"].get(entity["state"], {}).keys())

    # ----------------------------------------------------------- operations
    def _transition(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["entity_id", "vertical", "event"])
        if missing:
            return {
                "status": "error",
                "error": f"missing_required_input: {missing}",
                "available_operations": ["transition", "allowed", "machine", "replay"],
            }

        entity_id = data["entity_id"]
        vertical = data["vertical"]
        event = data["event"]
        actor = data.get("actor") or "system"
        transition_id = data.get("transition_id")

        try:
            entity = self._ensure_entity(entity_id, vertical)
        except ValueError as exc:
            return {"status": "error", "error": str(exc), "error_kind": error_kind(exc)}

        # Idempotent replay: same transition id returns the recorded outcome.
        if transition_id:
            prior = self.replayed[entity_id].get(transition_id)
            if prior is not None:
                return {**prior, "idempotent": True}

        preset = TRANSITIONS[vertical]
        state = entity["state"]
        legal = preset["states"].get(state, {})
        if event not in legal:
            return {
                "status": "error",
                "error": f"invalid_transition: {event} from {state}",
                "entity_id": entity_id,
                "current_state": state,
                "allowed_events": sorted(legal.keys()),
            }
        allowed_actors = ACTOR_RULES.get(event, [])
        if actor not in allowed_actors:
            return {
                "status": "error",
                "error": f"actor_not_permitted: {actor} cannot fire {event}",
                "allowed_actors": allowed_actors,
            }

        next_state = legal[event]
        entry = {
            "event": event,
            "actor": actor,
            "from": state,
            "to": next_state,
            "transition_id": transition_id,
            "timestamp": data.get("timestamp"),
        }
        entity["state"] = next_state
        entity["history"].append(entry)

        outcome = {
            "status": "success",
            "operation": "transition",
            "entity_id": entity_id,
            "vertical": vertical,
            "event": event,
            "actor": actor,
            "from_state": state,
            "to_state": next_state,
            "terminal": next_state in TERMINAL_STATES,
            "allowed_next": self._legal_events(entity),
            "history_length": len(entity["history"]),
            "transition": entry,
        }
        if transition_id:
            self.replayed[entity_id][transition_id] = dict(outcome)
        return outcome

    def _allowed(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["entity_id", "vertical"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        try:
            entity = self._ensure_entity(data["entity_id"], data["vertical"])
        except ValueError as exc:
            return {"status": "error", "error": str(exc), "error_kind": error_kind(exc)}
        return {
            "status": "success",
            "operation": "allowed",
            "entity_id": data["entity_id"],
            "current_state": entity["state"],
            "allowed_events": self._legal_events(entity),
            "terminal": entity["state"] in TERMINAL_STATES,
        }

    def _machine(self, data: Dict[str, Any]) -> Dict[str, Any]:
        vertical = data.get("vertical")
        if vertical is None:
            return {
                "status": "success",
                "operation": "machine",
                "verticals": KNOWN_VERTICALS,
                "actors": KNOWN_ACTORS,
                "terminal_states": sorted(TERMINAL_STATES),
            }
        preset = TRANSITIONS.get(vertical)
        if preset is None:
            return {
                "status": "error",
                "error": f"Unknown vertical: {vertical}",
                "known": KNOWN_VERTICALS,
            }
        return {
            "status": "success",
            "operation": "machine",
            "vertical": vertical,
            "initial": preset["initial"],
            "states": {s: sorted(events.keys()) for s, events in preset["states"].items()},
        }

    def _replay(self, data: Dict[str, Any]) -> Dict[str, Any]:
        sequence = data.get("sequence")
        if not isinstance(sequence, list) or not sequence:
            return {"status": "error", "error": "replay requires a non-empty sequence list"}
        vertical = data.get("vertical")
        if vertical is None:
            return {"status": "error", "error": "replay requires vertical"}
        # Replay against a scratch entity so real state is untouched.
        scratch_id = f"__replay__{data.get('entity_id') or 'anon'}"
        self.entities.pop(scratch_id, None)
        self.replayed.pop(scratch_id, None)
        results: List[Dict[str, Any]] = []
        for step in sequence:
            if not isinstance(step, dict):
                return {"status": "error", "error": "sequence entries must be objects"}
            results.append(
                self._transition(
                    {
                        "entity_id": scratch_id,
                        "vertical": vertical,
                        "event": step.get("event"),
                        "actor": step.get("actor") or "system",
                        "transition_id": step.get("transition_id"),
                    }
                )
            )
        last = results[-1] if results else {}
        return {
            "status": "success",
            "operation": "replay",
            "vertical": vertical,
            "steps": len(results),
            "final_state": last.get("to_state"),
            "failed": any(r.get("status") == "error" for r in results),
            "results": results,
        }
