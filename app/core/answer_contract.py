"""KERNEL_DEFAULTS K2 / K3 — the RAG answer contract.

These two claims live here, not in any one block, because every
rag-tagged answer layer has to say the same two things or the store
is lying in different voices.

K2  SOURCE-CLASS RENDERING
    Every chunk a RAG answer layer emits carries ``source_class``. The
    answer layer renders that class; a citation without a class is
    indistinguishable from one with a class, and that is the defect.

K3  COVERAGE HONESTY
    An answer that can measure its corpus says so with an ``N of M
    indexed`` line. Below 100% coverage the answer MUST NOT claim that
    something ``does-not-exist``: an incomplete index cannot support a
    negative existence claim. The cheap way to look complete is to
    pretend the missing tenth is not there.

WHY THIS IS A MODULE AND NOT A BLOCK
------------------------------------
There is no ``rag_core`` base class in this store (verified at
``ddda63f``: no module, no class, no kit by that name). Inventing one
so these rules had a parent would be a parallel architecture. The
contract is the parent. A block is RAG-derived when its tags include
``rag``, or when it is the kernel answerer (``grounded_answer``). Both
are required to go through the helpers below.

STORE-ENFORCED, THEN REPORTED
-----------------------------
The helpers raise :class:`AnswerContractViolation` when a caller tries
to emit an unclassified chunk or a ``does-not-exist`` claim on a
partial index. That is the gate. Lane 2's conformance table *also*
checks the same two claims, REPORT-ONLY, so the backlog is visible
without turning the store red. The flip to enforcing the table is a
separate PR.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Optional, Sequence

SOURCE_CLASS_KEY = "source_class"

#: The exact coverage line the answer contract requires. ``N`` and ``M``
#: are integers; the phrasing is pinned so a reader (and a conformance
#: check) can find it without guessing synonyms.
COVERAGE_LINE_TEMPLATE = "{n} of {m} indexed"

#: Phrases that assert negative existence. Matched case-insensitively.
#: The hyphenated form is the one the spec names; the spaced form is
#: the same claim in prose.
DOES_NOT_EXIST_PATTERNS = (
    re.compile(r"\bdoes-not-exist\b", re.I),
    re.compile(r"\bdoes not exist\b", re.I),
)


class AnswerContractViolation(ValueError):
    """An answer or chunk could not honestly be reported."""


def source_class_of(chunk: Mapping[str, Any]) -> str:
    """Read the class off a chunk or its metadata.

    An empty or missing class is not defaulted. Inventing
    ``unclassified`` would manufacture the very label this field exists
    to carry.
    """
    if not isinstance(chunk, Mapping):
        return ""
    raw = chunk.get(SOURCE_CLASS_KEY)
    if not raw:
        metadata = chunk.get("metadata")
        if isinstance(metadata, Mapping):
            raw = metadata.get(SOURCE_CLASS_KEY)
    if not isinstance(raw, str):
        return ""
    return raw.strip()


def emit_chunk(chunk: Mapping[str, Any]) -> dict:
    """Return a chunk dict that carries ``source_class`` at the top level.

    The class is copied from the chunk or its metadata. Absence is a
    defect: a caller that cannot name the class must not emit the chunk
    as a sourced citation.
    """
    if not isinstance(chunk, Mapping):
        raise AnswerContractViolation("chunk must be a mapping")
    emitted = dict(chunk)
    classified = source_class_of(chunk)
    if not classified:
        raise AnswerContractViolation(
            "every chunk must carry %s; a citation without a class is "
            "indistinguishable from one with a class" % SOURCE_CLASS_KEY
        )
    emitted[SOURCE_CLASS_KEY] = classified
    metadata = emitted.get("metadata")
    if isinstance(metadata, Mapping):
        merged = dict(metadata)
        merged[SOURCE_CLASS_KEY] = classified
        emitted["metadata"] = merged
    return emitted


def render_source_class(chunk: Mapping[str, Any]) -> str:
    """The line the answer layer shows for one chunk's class."""
    classified = source_class_of(chunk)
    if not classified:
        raise AnswerContractViolation(
            "cannot render %s: the chunk has none" % SOURCE_CLASS_KEY
        )
    return "%s: %s" % (SOURCE_CLASS_KEY, classified)


def render_citations(chunks: Iterable[Mapping[str, Any]]) -> list:
    """Emit every chunk with its class rendered.

    The returned list is what an answer payload's ``citations`` /
    ``sources`` field should carry. Each entry has ``source_class`` and
    ``source_class_line``.
    """
    rendered = []
    for chunk in chunks:
        emitted = emit_chunk(chunk)
        emitted["source_class_line"] = render_source_class(emitted)
        rendered.append(emitted)
    return rendered


def coverage_line(indexed: int, total: int) -> str:
    """``N of M indexed``. Both numbers must be honest counts.

    ``indexed`` is how many documents (or chunks, if that is the unit
    the index actually counts) are in the live index. ``total`` is the
    size of the corpus the answer is claiming to speak for. ``indexed``
    may not exceed ``total``.
    """
    if not isinstance(indexed, int) or isinstance(indexed, bool):
        raise AnswerContractViolation(
            "indexed must be an int, got %r" % (indexed,)
        )
    if not isinstance(total, int) or isinstance(total, bool):
        raise AnswerContractViolation("total must be an int, got %r" % (total,))
    if indexed < 0 or total < 0:
        raise AnswerContractViolation(
            "coverage counts cannot be negative (indexed=%r total=%r)"
            % (indexed, total)
        )
    if indexed > total:
        raise AnswerContractViolation(
            "indexed (%d) cannot exceed total (%d)" % (indexed, total)
        )
    return COVERAGE_LINE_TEMPLATE.format(n=indexed, m=total)


def coverage_fraction(indexed: int, total: int) -> Optional[float]:
    """``indexed / total``, or ``None`` when the total is zero.

    A zero-total corpus is not 0% covered and is not 100% covered — it
    is a corpus nobody can measure. ``None`` is the honest answer; see
    :mod:`app.core.block_result`.
    """
    line = coverage_line(indexed, total)  # validates
    del line
    if total == 0:
        return None
    return indexed / total


def is_fully_indexed(indexed: int, total: Optional[int]) -> bool:
    """True only when the live index is 100% of a known corpus."""
    if total is None:
        return False
    if total == 0:
        return False
    coverage_line(indexed, total)
    return indexed == total


def claims_does_not_exist(text: str) -> bool:
    """True when ``text`` asserts that something does not exist."""
    if not isinstance(text, str) or not text.strip():
        return False
    return any(pattern.search(text) for pattern in DOES_NOT_EXIST_PATTERNS)


def forbid_does_not_exist_claim(
    text: str,
    indexed: int,
    total: Optional[int],
) -> str:
    """Return ``text`` unchanged, or raise if it claims absence too soon.

    Below 100% coverage — and whenever coverage cannot be measured — a
    ``does-not-exist`` claim is a ContractViolation. The answer is
    still the caller's to write; this only refuses the dishonest one.
    """
    if not claims_does_not_exist(text):
        return text
    if is_fully_indexed(indexed, total):
        return text
    raise AnswerContractViolation(
        "does-not-exist is prohibited below 100 percent coverage "
        "(indexed=%r total=%r); an incomplete index cannot support a "
        "negative existence claim" % (indexed, total)
    )


def apply_answer_contract(
    *,
    chunks: Sequence[Mapping[str, Any]],
    answer_text: str,
    indexed: int,
    total: Optional[int],
) -> dict:
    """The answer payload K2 and K3 require.

    Always includes ``source_class`` on every citation and a coverage
    line when ``total`` is known. Refuses a ``does-not-exist`` claim
    when coverage is not 100%.
    """
    citations = render_citations(chunks)
    line = None if total is None else coverage_line(indexed, total)
    safe_text = forbid_does_not_exist_claim(answer_text, indexed, total)
    return {
        "answer": safe_text,
        "citations": citations,
        "coverage_line": line,
        "coverage": None if total is None else coverage_fraction(indexed, total),
        SOURCE_CLASS_KEY + "_rendered": True,
    }
