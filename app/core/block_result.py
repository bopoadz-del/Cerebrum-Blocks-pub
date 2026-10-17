"""The block result contract: what a block is allowed to say happened.

WHY THIS IS NOT ``StandardResponse``, AND NOT ``TypedBlock``
------------------------------------------------------------
Both already exist in this package, and neither covers this.

``app/core/response.py`` ``StandardResponse`` is the *envelope*
``UniversalBlock.execute`` wraps around whatever ``process`` returned: block
name, request id, timing, a two-valued ``status`` of ``success``/``error``.
It describes the call. It says nothing about what is inside ``result`` or
where those numbers came from.

``app/core/typed_block.py`` ``TypedBlock`` validates the *shape* of a block's
input and output against a declared schema. Shape is orthogonal to outcome:
a dict can satisfy every field of its schema and still be a guess.

``BlockResult`` is the third claim neither makes -- the *outcome*, and the
provenance of what is in ``data``. It composes with both rather than
replacing either: a ``TypedBlock`` may return a ``BlockResult`` as its data
payload, and ``execute`` will still wrap it in the usual envelope.

THE FOUR STATUSES
-----------------
``ok``
    The block did what was asked and stands behind all of ``data``.

``partial``
    Some of what was asked was done. ``coverage`` says how much, ``reason``
    says what is missing. A partial answer that presents itself as complete
    is the failure mode this status exists to make impossible.

``failed``
    The block could not do it. ``reason`` says why, in words a reader who is
    not holding the traceback can act on.

``refused``
    The block declined **on purpose**, because answering would have meant
    inventing something it had no source for.

WHY ``refused`` IS ITS OWN STATUS
---------------------------------
Folding refusal into ``failed`` teaches the scoreboard that declining to
invent an answer is a defect, and the cheapest way to raise a score under
that rule is to answer anyway. So refusal is separated at the type level and
the golden harness scores it as a pass: "I have no source for this" is the
correct answer to a question with no source, and a kit that says so is
working, not broken.

``partial`` is deliberately NOT in ``SCORED_AS_PASS``. The contract handed to
Lane 2 named only ``refused`` as a pass; whether a partial answer passes
depends on the coverage floor a harness sets, and that is not this module's
decision to make.

NEVER ``None``, NEVER RAISE-TO-HIDE
-----------------------------------
Every constructor validates. ``reason`` is mandatory whenever the status is
not ``ok``, because a bare "failed" is not a report -- it is the absence of
one, and it costs the reader the whole investigation. Construction raises on
a missing reason: that is a defect at the call site, and this module exists
to make it loud rather than let it ship.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

OK = "ok"
PARTIAL = "partial"
FAILED = "failed"
REFUSED = "refused"

#: The complete set. A status outside it is a defect, not a new state.
STATUSES = frozenset({OK, PARTIAL, FAILED, REFUSED})

#: What the golden harness counts as a pass. See "WHY refused IS ITS OWN
#: STATUS" above: an honest refusal is a correct answer, not a miss.
SCORED_AS_PASS = frozenset({OK, REFUSED})

#: Statuses that require a ``reason``.
REASON_REQUIRED = STATUSES - {OK}


class ContractViolation(ValueError):
    """A BlockResult was constructed that could not honestly be reported."""


@dataclass
class BlockResult:
    """What a block claims happened, and what backs the claim.

    Attributes:
        status: One of :data:`STATUSES`.
        reason: Why, in plain words. Mandatory unless ``status`` is ``ok``.
        coverage: How much of the request was answered, ``0.0``-``1.0``, or
            ``None`` when the block cannot honestly measure it. ``None`` is a
            legitimate answer and is not the same as ``0.0``.
        provenance: Where every number and definition in ``data`` came from.
            Extends the ``grounding`` field established in #82 -- see
            :func:`provenance_from_grounding`.
        evidence: References a reader can follow: chunk ids, document ids,
            file paths, tracebacks.
        data: The payload. Its shape is the block's own business (and
            ``TypedBlock``'s, if the block declares a schema).
    """

    status: str
    reason: Optional[str] = None
    coverage: Optional[float] = None
    provenance: List[Any] = field(default_factory=list)
    evidence: List[Any] = field(default_factory=list)
    data: Any = None

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ContractViolation(
                "unknown status %r (accepted: %s)"
                % (self.status, ", ".join(sorted(STATUSES)))
            )
        if self.status in REASON_REQUIRED and not (self.reason or "").strip():
            raise ContractViolation(
                "status %r requires a reason; a bare %r reports nothing and "
                "costs the reader the whole investigation"
                % (self.status, self.status)
            )
        if self.coverage is not None:
            if isinstance(self.coverage, bool) or not isinstance(
                self.coverage, (int, float)
            ):
                raise ContractViolation(
                    "coverage must be a number in 0..1 or None, got %r"
                    % (self.coverage,)
                )
            if not 0.0 <= float(self.coverage) <= 1.0:
                raise ContractViolation(
                    "coverage must lie in 0..1 or be None, got %r" % (self.coverage,)
                )
            self.coverage = float(self.coverage)
        # A caller passing one provenance record means one entry, not a
        # malformed result. Same for a single evidence ref.
        if isinstance(self.provenance, dict):
            self.provenance = [self.provenance]
        if isinstance(self.evidence, (dict, str)):
            self.evidence = [self.evidence]

    # -- constructors ------------------------------------------------------

    @classmethod
    def ok(cls, data: Any = None, **kwargs: Any) -> "BlockResult":
        return cls(status=OK, data=data, **kwargs)

    @classmethod
    def partial(cls, reason: str, data: Any = None, **kwargs: Any) -> "BlockResult":
        return cls(status=PARTIAL, reason=reason, data=data, **kwargs)

    @classmethod
    def failed(cls, reason: str, data: Any = None, **kwargs: Any) -> "BlockResult":
        return cls(status=FAILED, reason=reason, data=data, **kwargs)

    @classmethod
    def refused(cls, reason: str, data: Any = None, **kwargs: Any) -> "BlockResult":
        """Declined on purpose. Scored as a pass -- see the module docstring."""
        return cls(status=REFUSED, reason=reason, data=data, **kwargs)

    # -- reading -----------------------------------------------------------

    @property
    def is_ok(self) -> bool:
        return self.status == OK

    @property
    def scored_as_pass(self) -> bool:
        """True when the golden harness counts this as a pass."""
        return self.status in SCORED_AS_PASS

    def to_dict(self) -> Dict[str, Any]:
        """Serialise with every key present.

        Keys are never omitted, including when their value is ``None``. #82
        established why: a consumer reading ``result["provenance"]`` must not
        need to know which code path produced the result in order to avoid a
        ``KeyError``.
        """
        return {
            "status": self.status,
            "reason": self.reason,
            "coverage": self.coverage,
            "provenance": list(self.provenance),
            "evidence": list(self.evidence),
            "data": self.data,
        }


# -- provenance ------------------------------------------------------------


def provenance_from_grounding(
    grounding: Optional[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Turn #82's ``grounding`` dict into provenance entries.

    A ``grounded`` report yields one entry per definition that grounded the
    answer. The other three derivations yield a single entry recording
    exactly that: "nothing grounded this, and here is why" is provenance, and
    dropping it would leave an ungrounded number looking identical to a
    sourced one -- the defect #82 exists to prevent.
    """
    if not isinstance(grounding, dict):
        return []
    derivation = grounding.get("derivation")
    definitions = grounding.get("definitions") or []
    if definitions:
        return [
            {
                "derivation": derivation,
                "id": entry.get("id"),
                "tier": entry.get("tier"),
                "expression": entry.get("expression"),
                "key": entry.get("key"),
                "source": entry.get("provenance", {}),
            }
            for entry in definitions
        ]
    return [
        {
            "derivation": derivation,
            "id": None,
            "tier": None,
            "expression": None,
            "key": None,
            "source": {},
            "note": grounding.get("note"),
        }
    ]


# -- the adapter -----------------------------------------------------------

#: Legacy ``status`` strings mapped onto the four. Blocks in this store speak
#: ``UniversalBlock.execute``'s vocabulary (``success``/``error``); a few
#: already say ``ok``.
_LEGACY_STATUS = {
    "success": OK,
    "ok": OK,
    "succeeded": OK,
    "complete": OK,
    "completed": OK,
    "partial": PARTIAL,
    "error": FAILED,
    "failed": FAILED,
    "failure": FAILED,
    "refused": REFUSED,
    "refusal": REFUSED,
    "declined": REFUSED,
}

_REASON_KEYS = ("reason", "error", "message", "detail", "traceback")


def _reason_from(payload: Dict[str, Any], fallback: str) -> str:
    for key in _REASON_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value not in (None, "", [], {}):
            return str(value)
    return fallback


def to_block_result(raw: Any) -> BlockResult:
    """Wrap whatever a block returns today into a :class:`BlockResult`.

    This is why no existing block had to be edited. A legacy raw return -- a
    bare dict, a string, a number, a list -- becomes ``BlockResult.ok``
    carrying it as ``data``. A dict that already speaks the ``status``
    vocabulary is mapped onto the four statuses, and a ``grounding`` field is
    lifted into ``provenance``.

    ``None`` is the one raw return that does NOT become ``ok``. A block that
    returned nothing did not succeed quietly; it failed to say anything, and
    that is precisely what this contract exists to surface.

    ``confidence`` is deliberately NOT mapped onto ``coverage``. Confidence is
    how sure a block is about the answer it gave; coverage is how much of the
    question it answered. Conflating them would let a very sure answer to a
    tenth of the question read as nine-tenths done.
    """
    if isinstance(raw, BlockResult):
        return raw

    if raw is None:
        return BlockResult.failed(
            "the block returned None; it did not report an outcome"
        )

    if not isinstance(raw, dict):
        return BlockResult.ok(data=raw)

    provenance = provenance_from_grounding(raw.get("grounding"))
    declared = raw.get("status")
    key = declared.strip().lower() if isinstance(declared, str) else declared
    status = _LEGACY_STATUS.get(key)

    if status is None:
        # No status key at all -> a legacy raw return, which is ok. A status
        # nobody has taught us is NOT assumed to be fine.
        if declared in (None, ""):
            return BlockResult.ok(data=raw, provenance=provenance)
        return BlockResult.failed(
            "unrecognised legacy status %r" % (declared,),
            data=raw,
            provenance=provenance,
        )

    if status == OK:
        return BlockResult.ok(data=raw, provenance=provenance)
    if status == PARTIAL:
        return BlockResult.partial(
            _reason_from(
                raw, "the block reported a partial result without saying why"
            ),
            data=raw,
            provenance=provenance,
        )
    if status == REFUSED:
        return BlockResult.refused(
            _reason_from(raw, "the block refused without saying why"),
            data=raw,
            provenance=provenance,
        )
    return BlockResult.failed(
        _reason_from(raw, "the block reported an error without saying why"),
        data=raw,
        provenance=provenance,
    )
