"""Contract retrieval machinery ported from The_Fork.

Ported verbatim (exact line slices, donor comments preserved) from:

* The_Fork app/core/rag/retriever.py -- the named-contract fence
  (extract_contract_doc_ids / filename_matches_named_contracts /
  _contract_id_recency) and the answer-bearing-contract election
  (elect_answer_bearing_contract) with its full ask-shape closure
  (delay damages, engineer identity, TfC, DNP, ACA-incl-VAT, BOQ scope,
  BOQ item amount, part-summary total rescue predicates).
* The_Fork app/core/contract_data_chunks.py -- filled_particulars_rows /
  particulars_chunk_states_a_value and their parser closure.
* The_Fork app/core/rag/vector_store.py -- normalize_cesmm_item_codes.
* The_Fork app/core/rag/coverage_honesty.py -- the partial-index
  disclosure contract (below 100% the model may not say "does not exist").

NOT ported: the embedder/vector-store composition of retrieve() and the
full _ContractScope top-k fencing; this block carries the election and
the honesty contract, the platform's vector search stays the platform's.
Rescue toggles read the same env flags as the donor
(RAG_DELAY_DAMAGES_RATE_RESCUE, ...), all ON by default.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

# --- donor app/core/contract_data_chunks.py:L19-L21 (_CONTRACT_DATA_LABEL)
_CONTRACT_DATA_LABEL = (
    "CONTRACT DATA particulars — filled-in amount / duration / percentage"
)

# --- donor app/core/contract_data_chunks.py:L47-L47 (_CD_CLAUSE_LINE_RE)
_CD_CLAUSE_LINE_RE = re.compile(r"^\s*(\d+(?:\.\d+){1,3})\s+(\S.*)$")

# --- donor app/core/contract_data_chunks.py:L48-L48 (_CD_PIPE_ROW_RE)
_CD_PIPE_ROW_RE = re.compile(r"^\s*(.+?)\s*\|\s*(.+?)\s*$")

# --- donor app/core/contract_data_chunks.py:L49-L49 (_CD_DOT_LEADER_RE)
_CD_DOT_LEADER_RE = re.compile(r"^(.+?)\s*\.{3,}\s*(.+)$")

# --- donor app/core/contract_data_chunks.py:L50-L50 (_CD_TWO_COL_RE)
_CD_TWO_COL_RE = re.compile(r"^(.+?)\s{2,}(\S.*)$")

# --- donor app/core/contract_data_chunks.py:L51-L51 (_CD_SEP_ONLY_RE)
_CD_SEP_ONLY_RE = re.compile(r"^[\s|:\-–—]+$")

# --- donor app/core/contract_data_chunks.py:L52-L59 (_CD_FILLED_VALUE_RE)
_CD_FILLED_VALUE_RE = re.compile(
    r"(?i)(?:\b(?:sar|aed|usd|eur|gbp|qar|bhd|kwd|omr)\b|"
    r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|"
    r"\d[\d,]*\.\d{2}|"
    r"\d+(?:\.\d+)?\s*%|"
    r"\d+\s+(?:calendar\s+|working\s+)?days?|"
    r"\bnot\s+applicable\b|\bn/?a\b)"
)

# --- donor app/core/contract_data_chunks.py:L60-L64 (_CD_HIGH_SIGNAL_KEY_RE)
_CD_HIGH_SIGNAL_KEY_RE = re.compile(
    r"(?i)accepted\s+contract\s+amount|delay\s+damages|liquidated\s+damages|"
    r"time\s+for\s+completion|defects\s+notification|"
    r"performance\s+(?:bond|security|guarantee)|retention"
)

# --- donor app/core/contract_data_chunks.py:L153-L179 (_peel_trailing_filled_value)
def _peel_trailing_filled_value(text: str) -> tuple[str, str] | None:
    """Split a scanned Contract Data line whose value is glued to the key.

    Live A3/A5: OCR / table extraction yields
    ``1.1.75 Time for Completion for the whole of the Works 852 days``
    with no pipe, colon or dot-leader. The duration (or percentage) then
    lives in the key, so :func:`particulars_chunk_states_a_value` — which
    requires a value side — cannot see a filled particular, the unnamed
    election declines, and arrival order hands the pool to another
    package's schedule.

    Restricted to high-signal keys so a General Conditions sentence that
    happens to end in ``28 days`` is not treated as a particulars row.
    """
    raw = (text or "").strip()
    if not raw:
        return None
    match = _CD_FILLED_VALUE_RE.search(raw)
    if not match or match.start() < 8:
        return None
    key = raw[: match.start()].strip()
    val = raw[match.start():].strip()
    if not key or not val:
        return None
    if not _CD_HIGH_SIGNAL_KEY_RE.search(key):
        return None
    return key, val

# --- donor app/core/contract_data_chunks.py:L182-L206 (_split_key_value_line)
def _split_key_value_line(line: str) -> tuple[str, str] | None:
    stripped = (line or "").strip()
    if not stripped or _CD_SEP_ONLY_RE.match(stripped):
        return None
    for rx in (_CD_PIPE_ROW_RE, _CD_DOT_LEADER_RE, _CD_TWO_COL_RE):
        m = rx.match(stripped)
        if m:
            key, val = m.group(1).strip(), m.group(2).strip()
            if key and val:
                return key, val
    m = _CD_CLAUSE_LINE_RE.match(stripped)
    if m:
        clause, rest = m.group(1), m.group(2).strip()
        nested = None
        for rx in (_CD_PIPE_ROW_RE, _CD_DOT_LEADER_RE, _CD_TWO_COL_RE):
            nested = rx.match(rest)
            if nested:
                break
        if nested:
            return f"{clause} {nested.group(1).strip()}", nested.group(2).strip()
        peeled = _peel_trailing_filled_value(rest)
        if peeled:
            return f"{clause} {peeled[0]}", peeled[1]
        return f"{clause} {rest}", ""
    return _peel_trailing_filled_value(stripped)

# --- donor app/core/contract_data_chunks.py:L209-L222 (_is_cd_continuation)
def _is_cd_continuation(line: str) -> bool:
    raw = line or ""
    s = raw.strip()
    if not s:
        return False
    if _split_key_value_line(s) is not None:
        return False
    if _CD_CLAUSE_LINE_RE.match(s):
        return False
    if raw[:1] in " \t":
        return True
    if s.startswith("(") or s.startswith("["):
        return True
    return bool(_CD_FILLED_VALUE_RE.search(s))

# --- donor app/core/contract_data_chunks.py:L225-L258 (parse_contract_data_rows)
def parse_contract_data_rows(section: str) -> list[tuple[str, str]]:
    """Parse a Contract Data section into intact (key, value) rows.

    Continuation lines (indented amount-in-words, a lone currency figure)
    stay attached to the current key so digits and words of one particulars
    row are never split.
    """
    rows: list[tuple[str, str]] = []
    current_key = ""
    current_val = ""

    def _flush() -> None:
        nonlocal current_key, current_val
        key = current_key.strip()
        val = re.sub(r"\s+", " ", current_val).strip()
        if key:
            rows.append((key, val))
        current_key, current_val = "", ""

    for raw in (section or "").splitlines():
        if not raw.strip():
            continue
        if current_key and _is_cd_continuation(raw):
            current_val = f"{current_val} {raw.strip()}".strip()
            continue
        parsed = _split_key_value_line(raw)
        if parsed is None:
            if current_key:
                current_val = f"{current_val} {raw.strip()}".strip()
            continue
        _flush()
        current_key, current_val = parsed
    _flush()
    return rows

# --- donor app/core/contract_data_chunks.py:L326-L326 (_CD_ALNUM_RE)
_CD_ALNUM_RE = re.compile(r"[A-Za-z0-9]")

# --- donor app/core/contract_data_chunks.py:L329-L360 (particulars_chunk_states_a_value)
def particulars_chunk_states_a_value(chunk: str) -> bool:
    """True when a rendered particulars chunk carries at least one filled row.

    The counterpart to :func:`contract_data_particulars_chunks`: retrieval
    needs to tell a window that states a particular from one that is a list
    of unfilled keys, and only this module knows the rendered format.

    ``_format_cd_chunk`` writes a filled row as ``key: value`` and an empty
    one as a bare ``key``, so a colon with content after it IS the filled
    marker. Chunks from the raw-line fallback keep the document's own
    separator, so those are re-parsed with the same splitter the section
    parser uses.

    A value does not have to be a figure. ``1.3.1 (b) Engineer: <firm>`` and
    ``Schedule 10: Not Used`` are both filled in, and a numeric-only test
    cannot see either. It does have to say SOMETHING: a dot-leader run with
    nothing after it splits into a "value" made only of dots, which is an
    unfilled row drawn on paper.
    """
    lines = (chunk or "").splitlines()
    # Line 0 is the label this module prepends; every candidate carries it.
    for line in lines[1:]:
        stripped = line.strip()
        if not stripped:
            continue
        key, sep, val = stripped.partition(":")
        if sep and key.strip() and _CD_ALNUM_RE.search(val):
            return True
        parsed = _split_key_value_line(stripped)
        if parsed and _CD_ALNUM_RE.search(parsed[1]):
            return True
    return False

# --- donor app/core/contract_data_chunks.py:L363-L405 (filled_particulars_rows)
def filled_particulars_rows(chunk: str) -> list[tuple[str, str]]:
    """Filled ``(key, value)`` rows visible in a particulars chunk.

    Used by the unnamed-contract election so it can require that the
    *asked* label's value is filled, not merely that the window contains
    some other filled sibling plus the label as an unfilled key. Live
    A3/A5 on a two-year corpus: a DD-2022-175 window with a filled
    Accepted Contract Amount and a bare Time for Completion key used to
    lock the pool to the wrong year.

    Colon rows (named parties, ``Schedule N: Not Used``) are included —
    those values are not figures and the peel regex cannot see them.
    """
    lines = (chunk or "").splitlines()
    if not lines:
        return []
    start = 1 if _CONTRACT_DATA_LABEL.lower() in lines[0].lower() else 0
    body = "\n".join(lines[start:])
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _add(key: str, val: str) -> None:
        key, val = key.strip(), val.strip()
        if not key or not val or not _CD_ALNUM_RE.search(val):
            return
        item = (key, val)
        if item not in seen:
            seen.add(item)
            out.append(item)

    for key, val in parse_contract_data_rows(body):
        _add(key, val)
    for line in lines[start:]:
        stripped = line.strip()
        if not stripped:
            continue
        key, sep, val = stripped.partition(":")
        if sep:
            _add(key, val)
        parsed = _split_key_value_line(stripped)
        if parsed:
            _add(parsed[0], parsed[1])
    return out

# --- donor app/core/rag/vector_store.py:L66-L66 (_CESMM_OCR_SPACE_RE)
_CESMM_OCR_SPACE_RE = re.compile(r"\b([A-Za-z])[ \t]+(\d+\.\d+)\b")

# --- donor app/core/rag/vector_store.py:L70-L81 (normalize_cesmm_item_codes)
def normalize_cesmm_item_codes(text: str) -> str:
    """Collapse ``[A-Z]\\s+\\d+`` to ``[A-Z]\\d+`` in ``text``.

    Live WAVE 2 B5: Neon ``ILIKE '%D549.2%'`` was 0 hits while
    ``ILIKE '%D 549.2%'`` was 2 — Tesseract wrote the class letter and
    the digits as separate tokens. Callers must run this at index time
    (chunk text) and at query time (identifiers + match text) so either
    form retrieves the other. Empty/None input is returned unchanged.
    """
    if not text:
        return text
    return _CESMM_OCR_SPACE_RE.sub(r"\1\2", text)

# --- donor app/core/rag/retriever.py:L38-L43 (_REFERENCE_LABELS)
_REFERENCE_LABELS = (
    "BOQ", "Clause", "Contract", "Doc", "Document", "Drawing",
    "Item", "NCR", "Package", "PRC", "Ref", "Reference", "RFI",
    "Rev", "Revision", "Schedule", "Spec", "Specification", "VO",
    "Variation Order",
)

# --- donor app/core/rag/retriever.py:L46-L46 (_QUOTED_RE)
_QUOTED_RE = re.compile(r'["“]([^"”]{4,})["”]|\'([^\']{4,})\'')

# --- donor app/core/rag/retriever.py:L47-L47 (_CODE_TOKEN_RE)
_CODE_TOKEN_RE = re.compile(r"\b[A-Z]{2,}(?:[-./][A-Z0-9]+)+\b")

# --- donor app/core/rag/retriever.py:L50-L55 (_LABELED_REF_FULL_RE)
_LABELED_REF_FULL_RE = re.compile(
    r"\b(?P<label>" + "|".join(re.escape(l) for l in _REFERENCE_LABELS) + r")"
    r"\s*(?:No|Ref|Number|#)?\s*[:\-]?\s*"
    r"(?P<code>[A-Za-z0-9][A-Za-z0-9\-./]*)",
    re.IGNORECASE,
)

# --- donor app/core/rag/retriever.py:L58-L60 (_ALPHANUMERIC_RE)
_ALPHANUMERIC_RE = re.compile(
    r"\b(?=[A-Za-z0-9./\-]*\d)[A-Za-z0-9]{2,}(?:[./\-][A-Za-z0-9]{1,})+\b"
)

# --- donor app/core/rag/retriever.py:L62-L65 (_STOPWORDS)
_STOPWORDS: Set[str] = {
    "this", "that", "with", "from", "have", "what", "when", "where",
    "which", "about", "please", "thank", "thanks", "hello", "help",
}

# --- donor app/core/rag/retriever.py:L107-L107 (_MAX_CODE_ALPHA_RUN)
_MAX_CODE_ALPHA_RUN = 4

# --- donor app/core/rag/retriever.py:L110-L119 (_is_misspelled_word)
def _is_misspelled_word(token: str) -> bool:
    """True for a separator-free word with a digit typo'd into it."""
    if re.search(r"[-./]", token):
        return False  # separator tokens are handled by the segment rule above
    if not any(ch.isdigit() for ch in token):
        return False
    return any(
        len(run) > _MAX_CODE_ALPHA_RUN
        for run in re.findall(r"[A-Za-z]+", token)
    )

# --- donor app/core/rag/retriever.py:L131-L146 (_UNIT_ATOMS)
_UNIT_ATOMS = frozenset({
    "kg", "g", "mg", "t", "ton", "tonne", "lb", "kn", "mn", "n",
    "pa", "kpa", "mpa", "gpa", "bar", "psi",
    "mm", "cm", "m", "km", "in", "ft", "yd", "mil",
    "sqm", "cum", "rm", "lm", "ha",
    "l", "ml", "kl", "cc",
    "s", "sec", "min", "hr", "h",
    "w", "kw", "mw", "kwh", "wh", "v", "kv", "a", "ma", "hz", "khz",
    "c", "f", "k",
    "pcs", "pc", "no", "nos", "ea", "each", "unit",
    # Currencies in rate units (AED/m2, USD/ft2). Live 2026-08-20: a
    # self-coding conversion was identifier-miss short-circuited because
    # `aed/m2` contains a digit (the exponent) but is not a document code.
    "aed", "usd", "sar", "eur", "gbp", "qar", "bhd", "kwd", "omr", "egp",
    "cny", "inr", "jpy",
})

# --- donor app/core/rag/retriever.py:L149-L153 (_strip_exponent)
def _strip_exponent(seg: str) -> str:
    """'cm2' -> 'cm', 'm3' -> 'm', 'mm2' -> 'mm'; leaves 'd999' unchanged
    (only a SINGLE trailing exponent digit after an alpha base is stripped)."""
    m = re.fullmatch(r"([a-z]{1,4})([23])", seg)
    return m.group(1) if m else seg

# --- donor app/core/rag/retriever.py:L156-L168 (_looks_like_unit)
def _looks_like_unit(token: str) -> bool:
    """True when the token is a measurement unit or unit-ratio (kg/cm2, n/mm2,
    kn/m3, m3) rather than a document reference code. Ratios split on '/' (or the
    middot); every part, once its exponent is stripped, must be a known unit
    atom. A bare single unit (m3) also qualifies. Reference codes use '-'/'.'
    separators and non-unit alpha stems, so they are never flagged."""
    t = token.lower().strip()
    parts = [p for p in re.split(r"[/·]", t) if p]
    if not parts:
        return False
    if all(_strip_exponent(p) in _UNIT_ATOMS for p in parts):
        return True
    return False

# --- donor app/core/rag/retriever.py:L323-L325 (_CONTRACT_DOC_ID_RE)
_CONTRACT_DOC_ID_RE = re.compile(
    r"(?<![A-Za-z0-9])([A-Za-z]{2,}-\d{4}-\d+)(?![A-Za-z0-9])"
)

# --- donor app/core/rag/retriever.py:L328-L344 (extract_contract_doc_ids)
def extract_contract_doc_ids(text: str) -> List[str]:
    """Return lowercase PREFIX-YEAR-SEQ contract/doc ids in ``text``.

    Used to scope a named-contract question to that contract's files so a
    DD-2023 question cannot surface DD-2022 chunks. Empty when the text
    names no such id.
    """
    if not text:
        return []
    found: List[str] = []
    seen: Set[str] = set()
    for m in _CONTRACT_DOC_ID_RE.finditer(text):
        tok = m.group(1).lower()
        if tok not in seen:
            seen.add(tok)
            found.append(tok)
    return found

# --- donor app/core/rag/retriever.py:L370-L383 (_contract_id_recency)
def _contract_id_recency(cid: str) -> Tuple[int, int]:
    """Sort key for PREFIX-YEAR-SEQ: newer year, then higher sequence.

    Unnamed Master Corpus questions can retrieve a filled Time for
    Completion from more than one package (DD-2022-175 demolition at
    548 days, DD-2023-118 infrastructure at 852). First-in-rank used to
    lock the pool to whichever cosine arrived first. The later executed
    package owns the unnamed ask; the earlier one stays reachable by
    naming its id (#443).
    """
    parts = (cid or "").lower().split("-")
    year = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else -1
    seq = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else -1
    return (year, seq)

# --- donor app/core/rag/retriever.py:L847-L847 (logger)
logger = logging.getLogger(__name__)

# --- donor app/core/rag/retriever.py:L867-L891 (chunk_text)
def chunk_text(text: str, max_chars: int = 512, overlap: int = 50) -> List[str]:
    """Sliding-window chunker. Plain and deterministic — no spaCy, no
    LangChain, no semantic segmenter. Good enough for keyword-flavored
    retrieval over construction docs; the doc indexer's own
    ``chunk_text`` covers fancier cases when needed.

    Empty / whitespace-only input → empty list.
    """
    if not text or not text.strip():
        return []
    if max_chars <= overlap:
        raise ValueError(f"max_chars ({max_chars}) must exceed overlap ({overlap})")
    text = text.strip()
    if len(text) <= max_chars:
        return [text]
    chunks: List[str] = []
    step = max_chars - overlap
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start += step
    return chunks

# --- donor app/core/rag/retriever.py:L989-L995 (_GK_STOPWORDS)
_GK_STOPWORDS = frozenset({
    "what", "which", "when", "where", "whom", "whose", "does", "did", "how",
    "the", "and", "for", "are", "was", "were", "this", "that", "these", "those",
    "from", "with", "into", "your", "our", "their", "please", "tell", "give",
    "answer", "question", "about", "standard", "project", "document", "documents",
    "knowledge", "base", "using", "used", "there", "here", "have", "has", "will",
})

# --- donor app/core/rag/retriever.py:L1047-L1053 (_significant_terms)
def _significant_terms(query: str) -> frozenset:
    """Content words (>=4 chars, minus stopwords) used for lexical overlap."""
    import re as _re
    return frozenset(
        w for w in _re.findall(r"[a-z0-9]{4,}", (query or "").lower())
        if w not in _GK_STOPWORDS
    )

# --- donor app/core/rag/retriever.py:L1445-L1447 (_normalize_retrieval_ws)
def _normalize_retrieval_ws(text: str) -> str:
    """Collapse OCR / table newlines so a scanned label still matches."""
    return re.sub(r"\s+", " ", text or "").strip()

# --- donor app/core/rag/retriever.py:L1647-L1647 (_ACA_ASK_RE)
_ACA_ASK_RE = re.compile(r"(?i)accepted\s+contract\s+amount")

# --- donor app/core/rag/retriever.py:L1649-L1649 (_INCLUDING_VAT_RE)
_INCLUDING_VAT_RE = re.compile(r"(?i)including\s+vat|incl\.?\s+vat")

# --- donor app/core/rag/retriever.py:L2535-L2537 (_DEFINITION_QUESTION_RE)
_DEFINITION_QUESTION_RE = re.compile(
    r"(?i)\b(?:what\s+does\b.+\bmean|defin(?:e|ition\s+of)|meaning\s+of)\b",
)

# --- donor app/core/rag/retriever.py:L2538-L2544 (_PARTICULARS_FIELD_RE)
_PARTICULARS_FIELD_RE = re.compile(
    r"(?i)(?:excluding\s+vat|including\s+vat|accepted\s+contract\s+amount|"
    r"delay\s+damages|liquidated\s+damages|time\s+for\s+completion|"
    r"defects\s+notification|performance\s+(?:bond|security|guarantee)|"
    r"contract\s+data|appendix\s+to\s+(?:the\s+)?tender|"
    r"contract\s+particulars)",
)

# --- donor app/core/rag/retriever.py:L2548-L2559 (_ASKED_PARTICULAR_KEY_RES)
_ASKED_PARTICULAR_KEY_RES = (
    (re.compile(r"(?i)time\s+for\s+completion"), "time for completion"),
    (re.compile(r"(?i)delay\s+damages"), "delay damages"),
    (re.compile(r"(?i)liquidated\s+damages"), "liquidated damages"),
    (re.compile(r"(?i)defects\s+notification"), "defects notification"),
    (re.compile(r"(?i)accepted\s+contract\s+amount"), "accepted contract amount"),
    (re.compile(r"(?i)performance\s+bond"), "performance bond"),
    (re.compile(r"(?i)performance\s+security"), "performance security"),
    (re.compile(r"(?i)performance\s+guarantee"), "performance guarantee"),
    (re.compile(r"(?i)including\s+vat"), "including vat"),
    (re.compile(r"(?i)excluding\s+vat"), "excluding vat"),
)

# --- donor app/core/rag/retriever.py:L2560-L2564 (_FILLED_IN_ASK_RE)
_FILLED_IN_ASK_RE = re.compile(
    r"(?i)(?:how\s+many\s+days|what\s+is\s+the\s+(?:amount|rate|percentage|"
    r"duration|figure)|per\s+(?:calendar\s+)?day|calendar\s+days|"
    r"\bpercentage\b|\bamount\b)",
)

# --- donor app/core/rag/retriever.py:L2572-L2576 (_CD_CONTRACT_ROLE_RE)
_CD_CONTRACT_ROLE_RE = re.compile(
    r"(?i)\b(?:engineer(?:'s\s+representative)?|"
    r"employer(?:'s\s+representative)?|contractor|"
    r"dispute\s+(?:adjudication\s+)?board|adjudicator)\b",
)

# --- donor app/core/rag/retriever.py:L2577-L2580 (_CD_WHO_IS_RE)
_CD_WHO_IS_RE = re.compile(
    r"(?i)\bwho\s+(?:is|are)\b|\bname\s+of\s+the\b|"
    r"\bwhich\s+(?:firm|company|entity|organisation|organization)\b",
)

# --- donor app/core/rag/retriever.py:L2593-L2595 (_CD_SCHEDULE_ASK_RE)
_CD_SCHEDULE_ASK_RE = re.compile(
    r"(?i)\b(?:schedule|appendix|annex(?:ure)?)\s+(?:no\.?\s*)?\d+[A-Za-z]?\b",
)

# --- donor app/core/rag/retriever.py:L2596-L2599 (_CD_SCHEDULE_CONTEXT_RE)
_CD_SCHEDULE_CONTEXT_RE = re.compile(
    r"(?i)\b(?:contract|contracts|volume|volumes|"
    r"conditions\s+of\s+contract|tender)\b",
)

# --- donor app/core/rag/retriever.py:L2606-L2608 (_CD_MONEY_ARITHMETIC_ASK_RE)
_CD_MONEY_ARITHMETIC_ASK_RE = re.compile(
    r"(?i)\b(?:calculate|compute|work\s+out|how\s+much)\b",
)

# --- donor app/core/rag/retriever.py:L2609-L2612 (_CD_MONEY_UNIT_ASK_RE)
_CD_MONEY_UNIT_ASK_RE = re.compile(
    r"(?i)\b(?:sar|aed|usd|eur|gbp|qar|bhd|kwd|omr)\b|"
    r"\bmonetary\b|\bamount\s+per\b|\bvalue\s+per\b",
)

# --- donor app/core/rag/retriever.py:L2615-L2618 (_CD_MONETARY_VALUE_RE)
_CD_MONETARY_VALUE_RE = re.compile(
    r"(?i)\b(?:sar|aed|usd|eur|gbp|qar|bhd|kwd|omr)\b[^\n]{0,12}"
    r"\d{1,3}(?:,\d{3})+(?:\.\d+)?",
)

# --- donor app/core/rag/retriever.py:L2623-L2626 (_BOQ_SCOPE_ASK_RE)
_BOQ_SCOPE_ASK_RE = re.compile(
    r"(?i)\bbo[q]\b|\bbill\s+of\s+quantit|\bschedule\s+of\s+quantit|"
    r"\bmeasured\s+(?:work|works|items?|quantit)|\bpriced\s+bill\b",
)

# --- donor app/core/rag/retriever.py:L2627-L2629 (_CD_PARTICULARS_PREFIX_RE)
_CD_PARTICULARS_PREFIX_RE = re.compile(
    r"contract\s+data\s+particulars", re.IGNORECASE,
)

# --- donor app/core/rag/retriever.py:L2630-L2634 (_CD_HEADING_IN_CHUNK_RE)
_CD_HEADING_IN_CHUNK_RE = re.compile(
    r"(?:contract\s+data|appendix\s+to\s+(?:the\s+)?tender|"
    r"contract\s+particulars)",
    re.IGNORECASE,
)

# --- donor app/core/rag/retriever.py:L2659-L2664 (_CD_XREF_LEAD_RE)
_CD_XREF_LEAD_RE = re.compile(
    r"(?i)\b(?:stated|set\s+out|specified|given|listed|described|defined|"
    r"identified|named|shown|provided|inserted|entered|contained|"
    r"referred\s+to|required)?\s*"
    r"\b(?:in|within|under|per|to|of|from|into)\s+(?:the\s+)?$",
)

# --- donor app/core/rag/retriever.py:L2665-L2665 (_CD_XREF_LOOKBACK)
_CD_XREF_LOOKBACK = 48

# --- donor app/core/rag/retriever.py:L2674-L2676 (_CD_WHOLE_WORKS_QUERY_RE)
_CD_WHOLE_WORKS_QUERY_RE = re.compile(
    r"(?i)\bwhole\s+of\s+the\s+works\b|\bwhole\s+works\b|\bworks\s+as\s+a\s+whole\b",
)

# --- donor app/core/rag/retriever.py:L2677-L2677 (_CD_MILESTONE_QUERY_RE)
_CD_MILESTONE_QUERY_RE = re.compile(r"(?i)\bmilestones?\b")

# --- donor app/core/rag/retriever.py:L2678-L2678 (_CD_MILESTONE_CHUNK_RE)
_CD_MILESTONE_CHUNK_RE = re.compile(r"(?i)\bmilestones?\b")

# --- donor app/core/rag/retriever.py:L2703-L2703 (_CD_LABEL_TERM_BONUS)
_CD_LABEL_TERM_BONUS = 0.35

# --- donor app/core/rag/retriever.py:L2704-L2704 (_CD_LABEL_BONUS_CAP)
_CD_LABEL_BONUS_CAP = 1.40

# --- donor app/core/rag/retriever.py:L2707-L2711 (_cd_chunk_body)
def _cd_chunk_body(text: str) -> str:
    """Chunk text minus the identical particulars header line."""
    t = text or ""
    nl = t.find("\n")
    return t[nl + 1:] if nl != -1 else t

# --- donor app/core/rag/retriever.py:L2714-L2722 (_cd_label_bonus)
def _cd_label_bonus(query_terms: frozenset, text: str) -> float:
    """Reward a particulars row for containing the label the query names."""
    if not query_terms:
        return 0.0
    body = _cd_chunk_body(text).lower()
    if not body:
        return 0.0
    overlap = sum(1 for t in query_terms if t in body)
    return min(overlap * _CD_LABEL_TERM_BONUS, _CD_LABEL_BONUS_CAP)

# --- donor app/core/rag/retriever.py:L2725-L2741 (contract_data_mention_is_only_a_cross_reference)
def contract_data_mention_is_only_a_cross_reference(text: str) -> bool:
    """True when every "Contract Data" mention points AT it rather than IS it.

    ``... at the rate stated in the Contract Data for every calendar day ...``
    is a clause telling the reader where to look. ``Contract Data`` on its own
    line, followed by rows, is the thing itself. False when the chunk has no
    mention at all — the caller has already established there is one.
    """
    t = text or ""
    mentions = list(_CD_HEADING_IN_CHUNK_RE.finditer(t))
    if not mentions:
        return False
    for m in mentions:
        lead = t[max(0, m.start() - _CD_XREF_LOOKBACK):m.start()]
        if not _CD_XREF_LEAD_RE.search(lead):
            return False
    return True

# --- donor app/core/rag/retriever.py:L2744-L2759 (is_contract_data_particulars_row)
def is_contract_data_particulars_row(text: str) -> bool:
    """True for an index-time ``CONTRACT DATA particulars`` chunk that states
    a particular — the "answer-bearing Contract Data evidence" predicate the
    unnamed contract election runs on (:func:`elect_answer_bearing_contract`).

    Deliberately stricter than the scoring tier below, which asks only "is
    this a particulars chunk". The election decides which contract owns the
    whole result set, so it must be satisfied by a row that carries a VALUE
    and not by a window of unfilled keys — a clause number like ``1.1.67``
    reads as a decimal to the numeric test, so numbers alone are not proof
    that anything is filled in.
    """
    t = text or ""
    if not _CD_PARTICULARS_PREFIX_RE.search(t):
        return False
    return particulars_chunk_states_a_value(t)

# --- donor app/core/rag/retriever.py:L2762-L2791 (_asked_particular_key_phrases)
def _asked_particular_key_phrases(query: str) -> Tuple[str, ...]:
    """The Contract Data label(s) an unnamed ask is actually requesting.

    Term-overlap on the chunk body is too weak: ``works`` / ``completion``
    appear on a Volume 4 programme note and on an unfilled TfC key sitting
    next to a filled Accepted Contract Amount. Election must see the
    asked field on the *key* of a filled row.
    """
    q = (query or "").strip()
    if not q:
        return ()
    phrases: List[str] = []
    for rx, phrase in _ASKED_PARTICULAR_KEY_RES:
        if rx.search(q):
            phrases.append(phrase)
    if _CD_WHO_IS_RE.search(q):
        for m in _CD_CONTRACT_ROLE_RE.finditer(q):
            role = re.sub(r"\s+", " ", m.group(0).lower()).strip()
            if role:
                phrases.append(role)
    for m in _CD_SCHEDULE_ASK_RE.finditer(q):
        phrases.append(re.sub(r"\s+", " ", m.group(0).lower()).strip())
    # Dedup, keep order.
    seen: Set[str] = set()
    out: List[str] = []
    for p in phrases:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return tuple(out)

# --- donor app/core/rag/retriever.py:L2830-L2832 (_collapse_retrieval_ws)
def _collapse_retrieval_ws(text: str) -> str:
    """Collapse OCR / table newlines so a scanned label still matches."""
    return re.sub(r"\s+", " ", text or "").strip()

# --- donor app/core/rag/retriever.py:L2835-L2838 (_env_flag_on)
def _env_flag_on(name: str, default: str = "1") -> bool:
    return (os.getenv(name, default) or "").strip().lower() not in (
        "0", "false", "no", "off",
    )

# --- donor app/core/rag/retriever.py:L2841-L2846 (delay_damages_rate_rescue_enabled)
def delay_damages_rate_rescue_enabled() -> bool:
    """ON by default — live A5 recall after the #501 year-lock.

    RAG_DELAY_DAMAGES_RATE_RESCUE=0 restores prefix-only ranking.
    """
    return _env_flag_on("RAG_DELAY_DAMAGES_RATE_RESCUE")

# --- donor app/core/rag/retriever.py:L2849-L2858 (delay_damages_daily_rescue_enabled)
def delay_damages_daily_rescue_enabled() -> bool:
    """ON by default — live E1 rate × ACA recall after #520.

    A5 rate rescue is exclusive (fence drops every non-rate chunk).
    E1 needs the rate AND the Accepted Contract Amount; cosine on a
    3k-doc corpus ranks Spec TOC / Daywork / insurance over scanned
    Contract Data. RAG_DELAY_DAMAGES_DAILY_RESCUE=0 restores that FAIL.
    Distinct from COMPOSE_DELAY_DAMAGES_DAILY (the multiply step).
    """
    return _env_flag_on("RAG_DELAY_DAMAGES_DAILY_RESCUE")

# --- donor app/core/rag/retriever.py:L2861-L2866 (engineer_identity_rescue_enabled)
def engineer_identity_rescue_enabled() -> bool:
    """ON by default — live A9 Engineer appointment vs PSA parties.

    RAG_ENGINEER_IDENTITY_RESCUE=0 restores prefix-only ranking.
    """
    return _env_flag_on("RAG_ENGINEER_IDENTITY_RESCUE")

# --- donor app/core/rag/retriever.py:L2905-L2914 (query_asks_who_the_engineer_is)
def query_asks_who_the_engineer_is(query: str) -> bool:
    """True for A9 ("who is the Engineer"), not the Representative (D1)."""
    q = query or ""
    if not q or _DEFINITION_QUESTION_RE.search(q):
        return False
    if not _CD_WHO_IS_RE.search(q):
        return False
    if re.search(r"(?i)engineer'?s\s+representative", q):
        return False
    return bool(re.search(r"(?i)\bengineer\b", q))

# --- donor app/core/rag/retriever.py:L2917-L2917 (_DELAY_RATE_KEY_RE)
_DELAY_RATE_KEY_RE = re.compile(r"(?i)(?:delay|liquidated)\s+damages")

# --- donor app/core/rag/retriever.py:L2918-L2920 (_DELAY_CAP_KEY_RE)
_DELAY_CAP_KEY_RE = re.compile(
    r"(?i)\b(?:maximum|max(?:imum)?\s+amount|capped?)\b",
)

# --- donor app/core/rag/retriever.py:L2921-L2923 (_DELAY_RATE_VALUE_RE)
_DELAY_RATE_VALUE_RE = re.compile(
    r"(?i)\d+(?:\.\d+)?\s*%[^\n]{0,80}\bper\b",
)

# --- donor app/core/rag/retriever.py:L2924-L2926 (_DELAY_RATE_POINTER_RE)
_DELAY_RATE_POINTER_RE = re.compile(
    r"(?i)at\s+the\s+rate\s+stated\s+in\s+the\s+contract\s+data",
)

# --- donor app/core/rag/retriever.py:L2927-L2929 (_ENGINEER_GLOSSARY_RE)
_ENGINEER_GLOSSARY_RE = re.compile(
    r'(?i)"?engineer"?\s+means\s+the\s+person',
)

# --- donor app/core/rag/retriever.py:L2930-L2930 (_ENGINEER_REP_RE)
_ENGINEER_REP_RE = re.compile(r"(?i)engineer'?s\s+representative")

# --- donor app/core/rag/retriever.py:L2931-L2931 (_ENGINEER_KEY_RE)
_ENGINEER_KEY_RE = re.compile(r"(?i)\bengineer\b")

# --- donor app/core/rag/retriever.py:L2932-L2935 (_NOT_A_PARTY_NAME_RE)
_NOT_A_PARTY_NAME_RE = re.compile(
    r"(?i)^(?:the\s+)?(?:person\s+appointed|consultant|client|"
    r"employer|contractor|engineer)\s*$",
)

# --- donor app/core/rag/retriever.py:L2936-L2938 (_PARTY_FIRM_RE)
_PARTY_FIRM_RE = re.compile(
    r"(?i)\b(?:limited|ltd\.?|llc|llp|gmbh|plc|inc\.?)\b",
)

# --- donor app/core/rag/retriever.py:L2939-L2943 (_SCANNED_ENGINEER_LINE_RE)
_SCANNED_ENGINEER_LINE_RE = re.compile(
    r"(?im)^[ \t]*(?:\d+(?:\.\d+)+\s*(?:\([a-z]\))?\s*)?"
    r"(?:(?:the|name\s+of\s+the)\s+)?"
    r"engineer\b(?!\s*'?s\s+representative)[ \t]*[:|–-]?\s*(.*)$",
)

# --- donor app/core/rag/retriever.py:L2944-L2947 (_ENGINEER_IS_RE)
_ENGINEER_IS_RE = re.compile(
    r"(?i)\b(?:the\s+|name\s+of\s+the\s+)?engineer\b"
    r"(?!\s*'?s\s+representative)\s*(?:is|are|:)\s+(.{4,80})"
)

# --- donor app/core/rag/retriever.py:L2948-L2951 (_ENGINEER_POINTER_VAL_RE)
_ENGINEER_POINTER_VAL_RE = re.compile(
    r"(?i)^(?:named|stated|identified|appointed|set\s+out|specified|"
    r"defined|described|referred\s+to)\s+(?:in|as|under)\b"
)

# --- donor app/core/rag/retriever.py:L2954-L2964 (_looks_like_appointed_party)
def _looks_like_appointed_party(val: str) -> bool:
    """True when a particulars value is a firm / person, not a role word."""
    name = re.sub(r"\s+", " ", (val or "")).strip(" \t.:;,-")
    if len(name) < 4 or _NOT_A_PARTY_NAME_RE.match(name):
        return False
    if _ENGINEER_POINTER_VAL_RE.search(name):
        return False
    if _PARTY_FIRM_RE.search(name):
        return True
    letters = re.sub(r"[^A-Za-z]", "", name)
    return len(letters) >= 4 and any(ch.isupper() for ch in name)

# --- donor app/core/rag/retriever.py:L2967-L2970 (_delay_damages_key_is_rate)
def _delay_damages_key_is_rate(key: str) -> bool:
    if not _DELAY_RATE_KEY_RE.search(key or ""):
        return False
    return not _DELAY_CAP_KEY_RE.search(key or "")

# --- donor app/core/rag/retriever.py:L2973-L2995 (chunk_states_delay_damages_rate)
def chunk_states_delay_damages_rate(text: str) -> bool:
    """True when the chunk states the daily Delay Damages *rate*.

    A cap row (``Maximum amount of delay damages: 10%…``) and a General
    Conditions pointer (``at the rate stated in the Contract Data``)
    both contain the label and used to satisfy the unnamed election /
    reservation. Live A5 after #501 then cited 118 without the 0.1%
    per-calendar-day figure. The rate lives in a different chunk.
    """
    t = text or ""
    if not t or _DELAY_RATE_POINTER_RE.search(t):
        return False
    for key, val in filled_particulars_rows(t):
        if _delay_damages_key_is_rate(key) and _DELAY_RATE_VALUE_RE.search(val):
            return True
    blob = _collapse_retrieval_ws(t)
    if _DELAY_RATE_POINTER_RE.search(blob):
        return False
    if _DELAY_CAP_KEY_RE.search(blob) and not _DELAY_RATE_VALUE_RE.search(blob):
        return False
    if not _DELAY_RATE_KEY_RE.search(blob):
        return False
    return bool(_DELAY_RATE_VALUE_RE.search(blob))

# --- donor app/core/rag/retriever.py:L2998-L3043 (chunk_states_engineer_identity)
def chunk_states_engineer_identity(text: str) -> bool:
    """True when the chunk *appoints* the Engineer (live A9).

    A glossary ``"Engineer" means the person appointed…`` and a PSA
    Client/Consultant party list are lookalikes. The appointment is a
    filled ``1.3.1 (b) Engineer`` row (or a scanned line with a firm
    name). Engineer's Representative is D1 / corpus-blocked — do not
    invent a signatory.
    """
    t = text or ""
    if not t:
        return False
    for key, val in filled_particulars_rows(t):
        if _ENGINEER_REP_RE.search(key):
            continue
        if _ENGINEER_KEY_RE.search(key) and _looks_like_appointed_party(val):
            return True
    if _ENGINEER_GLOSSARY_RE.search(t) and not filled_particulars_rows(t):
        return False
    lines = (t or "").splitlines()
    for i, line in enumerate(lines):
        m = _SCANNED_ENGINEER_LINE_RE.match(line)
        if not m:
            continue
        rest = (m.group(1) or "").strip()
        nxt = ""
        nxt2 = ""
        if i + 1 < len(lines):
            nxt = lines[i + 1].strip()
        if i + 2 < len(lines):
            nxt2 = lines[i + 2].strip()
        for cand in (
            rest, nxt, nxt2,
            f"{rest} {nxt}".strip(),
            f"{nxt} {nxt2}".strip(),
        ):
            if _looks_like_appointed_party(cand):
                return True
    blob = _collapse_retrieval_ws(t)
    for named in _ENGINEER_IS_RE.finditer(blob):
        cand = named.group(1)
        if _looks_like_appointed_party(cand) and (
            _PARTY_FIRM_RE.search(cand) or re.search(r"\b[A-Z]{3,}\b", cand)
        ):
            return True
    return False

# --- donor app/core/rag/retriever.py:L3161-L3161 (_TFC_DAYS_RE)
_TFC_DAYS_RE = re.compile(r"(?i)\b(\d{2,4})\s+(?:calendar\s+|working\s+)?days\b")

# --- donor app/core/rag/retriever.py:L3162-L3165 (_TFC_PERMIT_TRACKER_RE)
_TFC_PERMIT_TRACKER_RE = re.compile(
    r"(?i)permit[- ]track|commencement[- ]completion|"
    r"community\s+[a-z0-9-]+\s+\w{3}-\d{2}\s+to\s+\w{3}-\d{2}",
)

# --- donor app/core/rag/retriever.py:L3168-L3171 (_TFC_SECTIONAL_RE)
_TFC_SECTIONAL_RE = re.compile(
    r"(?i)\bsection(?:al)?s?\s+"
    r"(?:\d+|[ivxlcd]+|[a-z]\b|of\s+(?:the\s+)?works)",
)

# --- donor app/core/rag/retriever.py:L3172-L3172 (_TFC_CLAUSE_1175_RE)
_TFC_CLAUSE_1175_RE = re.compile(r"(?i)\b1\.1\.75\b")

# --- donor app/core/rag/retriever.py:L3173-L3176 (_TFC_POINTER_RE)
_TFC_POINTER_RE = re.compile(
    r"(?i)(?:stated|named|identified|set\s+out|specified|defined|"
    r"described|referred\s+to)\s+in\s+(?:the\s+)?contract\s+data",
)

# --- donor app/core/rag/retriever.py:L3177-L3181 (_TFC_NOTICE_DAYS_RE)
_TFC_NOTICE_DAYS_RE = re.compile(
    r"(?i)\b(?:within|not\s+later\s+than|no\s+later\s+than|"
    r"after\s+(?:the\s+)?(?:taking[- ]over|toc)|before\s+the)\s+"
    r"(\d{2,4})\s+(?:calendar\s+|working\s+)?days",
)

# --- donor app/core/rag/retriever.py:L3184-L3189 (aca_including_vat_rescue_enabled)
def aca_including_vat_rescue_enabled() -> bool:
    """ON by default — live A2 answered delay damages / excl-VAT.

    RAG_ACA_INCLUDING_VAT_RESCUE=0 restores filename-only ACA ranking.
    """
    return _env_flag_on("RAG_ACA_INCLUDING_VAT_RESCUE")

# --- donor app/core/rag/retriever.py:L3192-L3197 (time_for_completion_rescue_enabled)
def time_for_completion_rescue_enabled() -> bool:
    """ON by default — live A3 missed the whole-Works TfC row.

    RAG_TIME_FOR_COMPLETION_RESCUE=0 restores prefix-only ranking.
    """
    return _env_flag_on("RAG_TIME_FOR_COMPLETION_RESCUE")

# --- donor app/core/rag/retriever.py:L3200-L3205 (dnp_rescue_enabled)
def dnp_rescue_enabled() -> bool:
    """ON by default — live A6 retrieved PSA / CPM TOC instead of DNP.

    RAG_DNP_RESCUE=0 restores Cosine / particulars-family ranking.
    """
    return _env_flag_on("RAG_DNP_RESCUE")

# --- donor app/core/rag/retriever.py:L3228-L3240 (query_asks_for_time_for_completion)
def query_asks_for_time_for_completion(query: str) -> bool:
    """True for A3 whole-Works TfC, not a milestone-only or sectional ask."""
    q = query or ""
    if not q or _DEFINITION_QUESTION_RE.search(q):
        return False
    if not re.search(r"(?i)time\s+for\s+completion", q):
        return False
    if _CD_MILESTONE_QUERY_RE.search(q) and not _CD_WHOLE_WORKS_QUERY_RE.search(q):
        return False
    # G2 / "Section 2 of the Works" is not the whole-Works particular.
    if _TFC_SECTIONAL_RE.search(q) and not _CD_WHOLE_WORKS_QUERY_RE.search(q):
        return False
    return True

# --- donor app/core/rag/retriever.py:L3243-L3250 (_tfc_key_is_not_whole_works)
def _tfc_key_is_not_whole_works(key: str) -> bool:
    """True when a TfC key is a milestone or section, not whole-of-Works."""
    k = key or ""
    if _CD_MILESTONE_CHUNK_RE.search(k):
        return True
    if _CD_WHOLE_WORKS_QUERY_RE.search(k):
        return False
    return bool(_TFC_SECTIONAL_RE.search(k))

# --- donor app/core/rag/retriever.py:L3253-L3273 (_tfc_row_is_whole_works)
def _tfc_row_is_whole_works(key: str, chunk_text: str = "") -> bool:
    """Positive test: this key is the whole-Works particular, not a lookalike.

    A Vol-2 sentence that mentions Time for Completion and peels
    ``within 90 days`` as a value is not clause 1.1.75.
    """
    k = key or ""
    if not k or _CD_MILESTONE_CHUNK_RE.search(k) or _TFC_SECTIONAL_RE.search(k):
        return False
    if _TFC_POINTER_RE.search(k):
        return False
    if _CD_WHOLE_WORKS_QUERY_RE.search(k) or _TFC_CLAUSE_1175_RE.search(k):
        return True
    if not re.search(r"(?i)time\s+for\s+completion", k):
        return False
    if len(k) > 96:
        return False
    return bool(
        _CD_PARTICULARS_PREFIX_RE.search(chunk_text or "")
        or _TFC_CLAUSE_1175_RE.search(chunk_text or "")
    )

# --- donor app/core/rag/retriever.py:L3299-L3328 (_tfc_days_from_block)
def _tfc_days_from_block(block: str) -> Optional[str]:
    """Days figure tied to the TfC label, not a neighbouring notice period."""
    blob = _normalize_retrieval_ws(block)
    if not blob:
        return None
    anchors = (
        _TFC_CLAUSE_1175_RE,
        re.compile(r"(?i)time\s+for\s+completion"),
        _CD_WHOLE_WORKS_QUERY_RE,
    )
    for rx in anchors:
        for m in rx.finditer(blob):
            window = blob[m.start(): m.end() + 120]
            if _tfc_key_is_not_whole_works(window):
                continue
            notice = _TFC_NOTICE_DAYS_RE.search(window)
            dm = _TFC_DAYS_RE.search(window)
            if not dm:
                continue
            if notice and notice.group(1) == dm.group(1):
                continue
            return f"{dm.group(1)} days"
    for dm in _TFC_DAYS_RE.finditer(blob):
        lead = blob[max(0, dm.start() - 48): dm.end() + 8]
        if _TFC_NOTICE_DAYS_RE.search(lead):
            continue
        if _tfc_key_is_not_whole_works(lead):
            continue
        return f"{dm.group(1)} days"
    return None

# --- donor app/core/rag/retriever.py:L3364-L3412 (chunk_states_accepted_contract_amount)
def chunk_states_accepted_contract_amount(text: str) -> bool:
    """True when the chunk states an Accepted Contract Amount in money.

    E1's rate base. Including-VAT and excluding-VAT both count —
    compose prefers excl when both are in the excerpts. A delay-damages
    rate row that only *names* the Contract Price / ACA is not this.
    A cap row (``10% of the Accepted Contract Amount``) has no SAR
    figure and fails the money test.
    """
    t = text or ""
    blob = _normalize_retrieval_ws(t).lower()
    if "accepted contract amount" not in blob:
        return False
    if not _CD_MONETARY_VALUE_RE.search(t):
        return False
    if _DELAY_RATE_KEY_RE.search(blob) and _DELAY_RATE_VALUE_RE.search(blob):
        for key, val in filled_particulars_rows(t):
            joined = f"{key} {val}".lower()
            if (
                "accepted contract amount" in joined
                and _CD_MONETARY_VALUE_RE.search(val)
                and not _DELAY_RATE_KEY_RE.search(key)
            ):
                break
        else:
            # Rate sentence is not the money row. A paired scanned
            # window that also carries the filled excl-VAT ACA still
            # is — do not drop it just because 8.8 shares the chunk.
            try:
                from app.lib.construction_formulas_commercial import (
                    chunk_has_real_accepted_contract_amount,
                )
                if not chunk_has_real_accepted_contract_amount(t):
                    return False
            except Exception:  # noqa: BLE001 — rate-only window is not ACA
                logger.debug("real-ACA test unavailable; treating as non-ACA", exc_info=True)
                return False
    try:
        from app.lib.construction_formulas_commercial import (
            chunk_accepted_contract_amount_is_only_toy,
            chunk_has_real_accepted_contract_amount,
        )
        if chunk_has_real_accepted_contract_amount(t):
            return True
        if chunk_accepted_contract_amount_is_only_toy(t):
            return False
    except Exception:  # noqa: BLE001 — never break a turn over an import
        logger.debug("toy-ACA test unavailable; treating money as ACA", exc_info=True)
    return True

# --- donor app/core/rag/retriever.py:L3560-L3586 (chunk_states_aca_including_vat)
def chunk_states_aca_including_vat(text: str) -> bool:
    """True when the chunk states Accepted Contract Amount *including VAT*.

    A delay-damages sentence that cites the excl-VAT ACA as the rate
    base (live A2) is the neighboring field, not this answer.
    """
    t = text or ""
    blob = _normalize_retrieval_ws(t).lower()
    if "accepted contract amount" not in blob:
        return False
    if not _INCLUDING_VAT_RE.search(blob):
        return False
    if not _CD_MONETARY_VALUE_RE.search(t):
        return False
    if _DELAY_RATE_KEY_RE.search(blob) and re.search(
        r"(?i)per\s+(?:calendar\s+)?day", blob,
    ):
        for key, val in filled_particulars_rows(t):
            joined = f"{key} {val}".lower()
            if (
                "accepted contract amount" in joined
                and _INCLUDING_VAT_RE.search(joined)
                and _CD_MONETARY_VALUE_RE.search(val)
            ):
                return True
        return False
    return True

# --- donor app/core/rag/retriever.py:L3589-L3644 (chunk_states_time_for_completion)
def chunk_states_time_for_completion(text: str) -> bool:
    """True when the chunk states whole-Works Time for Completion in days.

    Permit-tracker / community commencement-completion tables (live A3)
    mention completion dates but are not the Contract Data duration.
    Milestone-only and sectional rows are not this class. A Vol-2
    specification that only cites TfC and a ``within 90 days`` notice
    is a lookalike, not the particular.
    """
    t = text or ""
    if not t or _TFC_PERMIT_TRACKER_RE.search(t):
        return False
    blob = _normalize_retrieval_ws(t)
    if not re.search(r"(?i)time\s+for\s+completion", blob):
        return False
    if _CD_MILESTONE_CHUNK_RE.search(blob) and not _CD_WHOLE_WORKS_QUERY_RE.search(blob):
        return False
    if _TFC_SECTIONAL_RE.search(blob) and not _CD_WHOLE_WORKS_QUERY_RE.search(blob):
        return False
    for key, val in filled_particulars_rows(t):
        key_l = key.lower()
        if "time for completion" not in key_l:
            continue
        if not _tfc_row_is_whole_works(key, t):
            continue
        if _CD_PARTICULARS_PREFIX_RE.search(val or ""):
            continue
        if _TFC_DAYS_RE.search(val) or _TFC_DAYS_RE.search(key):
            return True
    if _CD_MILESTONE_CHUNK_RE.search(blob) and not _CD_WHOLE_WORKS_QUERY_RE.search(blob):
        return False
    if _TFC_POINTER_RE.search(blob) and not (
        _CD_PARTICULARS_PREFIX_RE.search(t)
        or (
            _CD_HEADING_IN_CHUNK_RE.search(t)
            and not contract_data_mention_is_only_a_cross_reference(t)
        )
    ):
        return False
    days = _tfc_days_from_block(t)
    if not days:
        return False
    if not (
        _CD_WHOLE_WORKS_QUERY_RE.search(blob)
        or _TFC_CLAUSE_1175_RE.search(blob)
        or _CD_PARTICULARS_PREFIX_RE.search(t)
        or (
            _CD_HEADING_IN_CHUNK_RE.search(t)
            and not contract_data_mention_is_only_a_cross_reference(t)
        )
    ):
        return False
    notice = _TFC_NOTICE_DAYS_RE.search(blob)
    if notice and notice.group(1) == days.split()[0]:
        return False
    return True

# --- donor app/core/rag/retriever.py:L3925-L3928 (_DNP_ASK_RE)
_DNP_ASK_RE = re.compile(
    r"(?i)(?:defects\s+notification(?:\s+period)?"
    r"|(?:what\s+is\s+(?:the\s+)?)dnp\b)"
)

# --- donor app/core/rag/retriever.py:L3929-L3929 (_DNP_KEY_RE)
_DNP_KEY_RE = re.compile(r"(?i)defects\s+notification(?:\s+period)?")

# --- donor app/core/rag/retriever.py:L3930-L3930 (_DNP_CLAUSE_RE)
_DNP_CLAUSE_RE = re.compile(r"(?i)\b1\.1\.27\b")

# --- donor app/core/rag/retriever.py:L3931-L3934 (_DNP_DURATION_RE)
_DNP_DURATION_RE = re.compile(
    r"(?i)\b(\d{1,4})\s+(?:calendar\s+|working\s+)?"
    r"(days?|months?|years?)\b"
)

# --- donor app/core/rag/retriever.py:L3935-L3938 (_DNP_POINTER_RE)
_DNP_POINTER_RE = re.compile(
    r"(?i)(?:stated|named|identified|set\s+out|specified|defined|"
    r"described|referred\s+to)\s+in\s+(?:the\s+)?contract\s+data"
)

# --- donor app/core/rag/retriever.py:L3939-L3941 (_DNP_GLOSSARY_RE)
_DNP_GLOSSARY_RE = re.compile(
    r"(?i)(?:defects\s+notification\s+period|\bdnp\b)\s+means\b"
)

# --- donor app/core/rag/retriever.py:L3942-L3944 (_DNP_TOC_RE)
_DNP_TOC_RE = re.compile(
    r"(?i)table\s+of\s+contents|document\s+register|\brecitals?\b"
)

# --- donor app/core/rag/retriever.py:L3948-L3966 (query_asks_for_defects_notification_period)
def query_asks_for_defects_notification_period(query: str) -> bool:
    """True for A6 (Defects Notification Period), not A2/A3/A5/A9/C1/E1/F1."""
    q = query or ""
    if not q or _DEFINITION_QUESTION_RE.search(q):
        return False
    if not _DNP_ASK_RE.search(q):
        return False
    # Neighboring-field asks that happen to mention DNP stay off this path.
    if _ACA_ASK_RE.search(q):
        return False
    if re.search(r"(?i)time\s+for\s+completion", q):
        return False
    if re.search(r"(?i)(?:delay|liquidated)\s+damages", q):
        return False
    if _CD_WHO_IS_RE.search(q):
        return False
    if _BOQ_SCOPE_ASK_RE.search(q):
        return False
    return True

# --- donor app/core/rag/retriever.py:L3969-L3978 (_format_dnp_duration)
def _format_dnp_duration(match: re.Match) -> str:
    num = match.group(1)
    unit = (match.group(2) or "days").lower()
    if unit.startswith("day"):
        return f"{num} days"
    if unit.startswith("month"):
        return f"{num} months"
    if unit.startswith("year"):
        return f"{num} years"
    return f"{num} {unit}"

# --- donor app/core/rag/retriever.py:L3981-L3996 (_dnp_duration_from_text)
def _dnp_duration_from_text(text: str) -> Optional[str]:
    """Duration tied to the DNP label, not a neighbouring notice period."""
    blob = _normalize_retrieval_ws(text)
    if not blob:
        return None
    for rx in (_DNP_KEY_RE, _DNP_CLAUSE_RE):
        for m in rx.finditer(blob):
            window = blob[m.start(): m.end() + 140]
            if _DNP_POINTER_RE.search(window) and not _DNP_DURATION_RE.search(window):
                continue
            if rx is _DNP_CLAUSE_RE and not _DNP_KEY_RE.search(window):
                continue
            dm = _DNP_DURATION_RE.search(window)
            if dm:
                return _format_dnp_duration(dm)
    return None

# --- donor app/core/rag/retriever.py:L3999-L4030 (chunk_states_defects_notification_period)
def chunk_states_defects_notification_period(text: str) -> bool:
    """True when the chunk states a Defects Notification Period duration.

    PSA / CPM table-of-contents, recitals, and document registers that
    only *name* the heading (live A6 on 82eb9c5) are lookalikes. A
    General Conditions pointer (``as stated in the Contract Data``) and
    a glossary ``means the period…`` are not the filled 1.1.27 row.
    """
    t = text or ""
    if not t:
        return False
    if _DNP_GLOSSARY_RE.search(t) and not filled_particulars_rows(t):
        return False
    for key, val in filled_particulars_rows(t):
        if not _DNP_KEY_RE.search(key):
            continue
        if _DNP_DURATION_RE.search(val) or _DNP_DURATION_RE.search(key):
            return True
    blob = _normalize_retrieval_ws(t)
    if _DNP_POINTER_RE.search(blob) and not (
        _CD_PARTICULARS_PREFIX_RE.search(t)
        or (
            _CD_HEADING_IN_CHUNK_RE.search(t)
            and not contract_data_mention_is_only_a_cross_reference(t)
        )
    ):
        return False
    if _DNP_TOC_RE.search(blob) and not (
        _CD_PARTICULARS_PREFIX_RE.search(t) or filled_particulars_rows(t)
    ):
        return False
    return bool(_dnp_duration_from_text(t))

# --- donor app/core/rag/retriever.py:L5200-L5200 (_RATE_ONLY_RE)
_RATE_ONLY_RE = re.compile(r"(?i)\brate\s*only\b")

# --- donor app/core/rag/retriever.py:L5202-L5204 (_ITEM_AMOUNT_ASK_RE)
_ITEM_AMOUNT_ASK_RE = re.compile(
    r"(?i)\b(?:total\s+amount|(?<!contract\s)amount|sum\s+for|value\s+for)\b",
)

# --- donor app/core/rag/retriever.py:L5205-L5207 (_UNIT_RATE_ONLY_ASK_RE)
_UNIT_RATE_ONLY_ASK_RE = re.compile(
    r"(?i)\b(?:unit\s+rate|rate\s+for|rate\s+per)\b",
)

# --- donor app/core/rag/retriever.py:L5208-L5208 (_CESMM_COMPACT_ITEM_RE)
_CESMM_COMPACT_ITEM_RE = re.compile(r"(?i)^[a-z]\d{2,4}(?:\.\d+)?$")

# --- donor app/core/rag/retriever.py:L5209-L5211 (_CESMM_IN_TEXT_RE)
_CESMM_IN_TEXT_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])([A-Z])\s*(\d{2,4}(?:\.\d+)?)(?![A-Za-z0-9])",
)

# --- donor app/core/rag/retriever.py:L5276-L5279 (_NEXT_CESMM_ROW_RE)
_NEXT_CESMM_ROW_RE = re.compile(
    r"(?i)(?:\s*[|]\s*([A-Z])\s*(\d{2,3}(?:\.\d{1,2})?)\b"
    r"|\s+([A-Z])\s*(\d{3}(?:\.\d{1,2})?)\b)",
)

# --- donor app/core/rag/retriever.py:L5280-L5280 (_CESMM_ROW_TAIL_CHARS)
_CESMM_ROW_TAIL_CHARS = 220

# --- donor app/core/rag/retriever.py:L5283-L5312 (_cesmm_row_windows)
def _cesmm_row_windows(text: str, code: str) -> List[str]:
    """Local row windows around one CESMM code.

    Amount sits to the right of the item code. A previous row's
    Rate Only must not stain the next item on a mixed BOQ page —
    including same-line OCR soup (live WAVE 2 B4/B5 on fa07b2f:
    D529.3 Rate Only + D549.2 fence + D599.5 carriageway in one
    scanned line). Cut at the next CESMM item on this or the next
    line; keep one continuation line so ``D 529.3`` / next-line
    ``Rate Only`` still belongs to D529.3.
    """
    compact = normalize_cesmm_item_codes(code or "")
    if not compact:
        return []
    letter, rest = compact[0], compact[1:]
    item_re = re.compile(
        rf"(?i)(?<![A-Za-z0-9]){re.escape(letter)}\s*{re.escape(rest)}"
        r"(?![A-Za-z0-9])",
    )
    blob = text or ""
    windows: List[str] = []
    for match in item_re.finditer(blob):
        tail = blob[match.end(): match.end() + _CESMM_ROW_TAIL_CHARS]
        cut = _NEXT_CESMM_ROW_RE.search(tail)
        if cut:
            tail = tail[:cut.start()]
        windows.append(
            _normalize_retrieval_ws(blob[match.start(): match.end()] + tail)
        )
    return windows

# --- donor app/core/rag/retriever.py:L5412-L5414 (_BOQ_CURRENCY_ATOM)
_BOQ_CURRENCY_ATOM = (
    r"(?:SAR|SR|AED|USD|EUR|GBP|QAR|BHD|KWD|OMR|EGP|CNY|INR|JPY|riyal[s]?)"
)

# --- donor app/core/rag/retriever.py:L5415-L5415 (_BOQ_CURRENCY_PREFIX)
_BOQ_CURRENCY_PREFIX = rf"(?:{_BOQ_CURRENCY_ATOM}\s+)?"

# --- donor app/core/rag/retriever.py:L5416-L5426 (_PRICED_BOQ_TRIPLE_RE)
_PRICED_BOQ_TRIPLE_RE = re.compile(
    r"(?i)(?P<qty>\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
    r"\s+"
    r"(?P<unit>m[2²³3]|sq\.?\s*m|lin\.?\s*m|nr|no\.?|item|sum|ls|m)\b"
    r"\s*[@]?\s*"
    + _BOQ_CURRENCY_PREFIX
    + r"(?P<rate>\d{1,3}(?:,\d{3})*(?:\.\d+)?)"
    + r"\s*[=]?\s*"
    + _BOQ_CURRENCY_PREFIX
    + r"(?P<amount>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d{2}|\d{4,})"
)

# --- donor app/core/rag/retriever.py:L5446-L5454 (_parse_boq_number)
def _parse_boq_number(raw: str) -> Optional[float]:
    tok = (raw or "").replace(",", "").strip()
    if not tok:
        return None
    try:
        return float(tok)
    except ValueError:
        logger.debug("BOQ number parse failed for %r", raw, exc_info=True)
        return None

# --- donor app/core/rag/retriever.py:L5457-L5498 (_parse_priced_cesmm_window)
def _parse_priced_cesmm_window(window: str, code: str) -> Optional[Dict[str, Any]]:
    """Qty / unit / rate / amount from one isolated CESMM row.

    A Rate Only / Excluded *status* with no triple is None. A valid
    qty × rate = amount still parses when a neighbor or page note
    says Rate Only (live WAVE 2 B5 Part Nr. 3 stain).
    """
    if not window:
        return None
    blob = _normalize_retrieval_ws((window or "").replace("|", " "))
    match = _PRICED_BOQ_TRIPLE_RE.search(blob)
    if not match:
        return None
    qty = _parse_boq_number(match.group("qty"))
    rate = _parse_boq_number(match.group("rate"))
    amount = _parse_boq_number(match.group("amount"))
    if qty is None or rate is None or amount is None:
        return None
    if qty <= 0 or rate <= 0 or amount <= 0:
        return None
    product = qty * rate
    tol = max(1.0, 0.015 * amount)
    if abs(product - amount) > tol:
        return None
    unit = _normalize_retrieval_ws(match.group("unit") or "")
    pretty = f"{code[0].upper()}{code[1:]}" if code and code[0].isalpha() else code
    letter, rest = (code[0], code[1:]) if code else ("", "")
    item_re = re.compile(
        rf"(?i)(?<![A-Za-z0-9]){re.escape(letter)}\s*{re.escape(rest)}"
        r"(?![A-Za-z0-9])",
    )
    code_m = item_re.search(blob)
    start = code_m.end() if code_m else 0
    desc = _normalize_retrieval_ws(blob[start:match.start()]).strip(" :-–—")
    return {
        "code": pretty,
        "description": desc,
        "qty": qty,
        "unit": unit,
        "rate": rate,
        "amount": amount,
    }

# --- donor app/core/rag/retriever.py:L5564-L5566 (_BOQ_PAGE_REF_RE)
_BOQ_PAGE_REF_RE = re.compile(
    r"(?i)\b([A-Za-z])\s*[/\-]\s*(\d{1,3})\s*[/\-]\s*(\d{1,3})\b"
)

# --- donor app/core/rag/retriever.py:L5567-L5570 (_PART_SUMMARY_LABEL_RE)
_PART_SUMMARY_LABEL_RE = re.compile(
    r"(?i)\b(?:part\s+summary|total\s+this\s+page|page\s+total|"
    r"carried\s+to\s+collection)\b"
)

# --- donor app/core/rag/retriever.py:L5571-L5573 (_PART_SUMMARY_ASK_RE)
_PART_SUMMARY_ASK_RE = re.compile(
    r"(?i)\bpart\s+summary\b|\btotal\s+this\s+page\b|\bpage\s+total\b"
)

# --- donor app/core/rag/retriever.py:L5574-L5576 (_PART_SUMMARY_BILL_RE)
_PART_SUMMARY_BILL_RE = re.compile(
    r"(?i)\b(?:bill|boq|demolit|site\s+clear|clearance)\b"
)

# --- donor app/core/rag/retriever.py:L5577-L5581 (_PART_SUMMARY_MONEY_RE)
_PART_SUMMARY_MONEY_RE = re.compile(
    r"(?i)"
    + _BOQ_CURRENCY_PREFIX
    + r"(?P<amount>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d{2}|\d{5,})"
)

# --- donor app/core/rag/retriever.py:L5601-L5610 (extract_asked_boq_page_refs)
def extract_asked_boq_page_refs(query: str) -> List[str]:
    """CESMM bill page refs the ask names (``d/3/1``)."""
    out: List[str] = []
    seen: Set[str] = set()
    for match in _BOQ_PAGE_REF_RE.finditer(query or ""):
        ref = f"{match.group(1).lower()}/{int(match.group(2))}/{int(match.group(3))}"
        if ref not in seen:
            seen.add(ref)
            out.append(ref)
    return out

# --- donor app/core/rag/retriever.py:L5613-L5619 (_normalize_boq_page_refs_in_text)
def _normalize_boq_page_refs_in_text(text: str) -> str:
    """Collapse OCR ``D / 3 / 1`` so a query ``d/3/1`` can match."""

    def _repl(match: re.Match) -> str:
        return f"{match.group(1).lower()}/{int(match.group(2))}/{int(match.group(3))}"

    return _BOQ_PAGE_REF_RE.sub(_repl, text or "")

# --- donor app/core/rag/retriever.py:L5759-L5781 (chunk_states_part_summary_total)
def chunk_states_part_summary_total(
    text: str, page_refs: Optional[List[str]] = None,
) -> bool:
    """True when the chunk prints a Part Summary / page-total figure.

    When ``page_refs`` is given, the asked page must appear in the
    chunk or the chunk must be a single unlabeled Part Summary row
    (header + footer split by the 500-char BOQ chunker).
    """
    blob = text or ""
    if not _PART_SUMMARY_LABEL_RE.search(blob):
        return False
    if not _PART_SUMMARY_MONEY_RE.search(
        _normalize_retrieval_ws(blob.replace("|", " "))
    ):
        return False
    if not page_refs:
        return True
    normalized = _normalize_boq_page_refs_in_text(blob)
    found = extract_asked_boq_page_refs(normalized)
    if found:
        return any(ref in found for ref in page_refs)
    return True

# --- donor app/core/rag/retriever.py:L6188-L6207 (query_asks_for_contract_particulars)
def query_asks_for_contract_particulars(query: str) -> bool:
    """True when the question wants a filled-in Contract Data particular.

    Definition questions ("what does Accepted Contract Amount mean") stay
    on the glossary path. Arithmetic unit-rate questions are not this.

    A particular is not always a figure: "who is the Engineer" asks for the
    filled row that names the party, which is why a contract-role identity
    ask counts here too.
    """
    q = (query or "").strip()
    if not q or _DEFINITION_QUESTION_RE.search(q):
        return False
    if _PARTICULARS_FIELD_RE.search(q):
        return True
    if _CD_WHO_IS_RE.search(q) and _CD_CONTRACT_ROLE_RE.search(q):
        return True
    if _CD_SCHEDULE_ASK_RE.search(q) and _CD_SCHEDULE_CONTEXT_RE.search(q):
        return True
    return bool(_FILLED_IN_ASK_RE.search(q) and _CD_HEADING_IN_CHUNK_RE.search(q))

# --- donor app/core/rag/retriever.py:L6210-L6218 (query_asks_for_boq_scope)
def query_asks_for_boq_scope(query: str) -> bool:
    """True when the question is about measured scope in a bill of quantities.

    The answer lives in BOQ item rows, not in the prose of a Conditions of
    Contract that happens to describe the same scope — and certainly not in
    another contract year's prose, which is what wave-2 F1 returned for all
    three of its citations.
    """
    return bool(_BOQ_SCOPE_ASK_RE.search((query or "").strip()))

# --- donor app/core/rag/retriever.py:L6221-L6238 (document_is_a_bill_of_quantities)
def document_is_a_bill_of_quantities(filename: str) -> bool:
    """True when the DOCUMENT NAME says it is a bill of quantities.

    Consumes ``doc_index.BOQ_FILENAME_RE`` rather than restating it, so the
    retrieval-side test cannot drift from the one the indexer already uses to
    pick a chunker and an OCR budget. The import is deferred because
    ``doc_index`` imports this module; it is reached only for a BOQ-shaped
    ask, and ``sys.modules`` caches it after the first.
    """
    name = filename or ""
    if not name:
        return False
    try:
        from app.core.doc_index import BOQ_FILENAME_RE
    except Exception as exc:  # noqa: BLE001 — never break a turn over this
        logger.warning("BOQ filename test unavailable: %s", exc)
        return False
    return bool(BOQ_FILENAME_RE.search(name))

# --- donor app/core/rag/retriever.py:L6241-L6254 (query_needs_a_monetary_base)
def query_needs_a_monetary_base(query: str) -> bool:
    """True when the ask is arithmetic over a particular and wants money out.

    A rate expressed as a percentage cannot answer "how much per day in SAR"
    on its own; the amount it is a percentage OF has to be in the excerpts
    too. Wave-2 E1 is the whole failure: the 0.1%-per-day row came back at
    rank 1 and the answer then reported the SAR figure as absent.
    """
    q = (query or "").strip()
    if not q:
        return False
    return bool(
        _CD_MONEY_ARITHMETIC_ASK_RE.search(q) and _CD_MONEY_UNIT_ASK_RE.search(q)
    )

# --- donor app/core/rag/retriever.py:L68-L80 (_is_prose_compound)
def _is_prose_compound(token: str) -> bool:
    """True if a hyphen/dot/slash token contains a full English-word segment
    (all-alpha, >4 chars) — e.g. '30-storey', '12-month', 'revision-3'. These
    are descriptive compounds, NOT reference codes (whose alpha parts are short
    abbreviations: TL, PRC, IP). Without this guard a generative request like
    "risk register for a 30-storey tower" extracted '30-storey' as a reference,
    which then (on a retrieval miss) wrongly fired the missing-reference
    short-circuit — answering "provide the exact filename" to a generate request.
    """
    for seg in re.split(r"[-./]", token):
        if seg.isalpha() and len(seg) > 4:
            return True
    return _is_misspelled_word(token)

# --- donor app/core/rag/retriever.py:L171-L259 (extract_query_identifiers)
def extract_query_identifiers(query: str) -> List[str]:
    """Pull construction reference identifiers out of a user query.

    Detects, without hardcoding any specific value:
      * quoted phrases (preserved as exact-match candidates)
      * code-shaped tokens such as PRC-501, PK-INF-002-0000-...
      * labeled references such as "VO Ref 31", "RFI 42", "Clause 13.1"
      * alphanumeric tokens that clearly contain a digit (e.g. D999.46)

    Returns a deduplicated list of lowercase identifier strings. The list
    is empty for queries that contain no identifier-like tokens.
    """
    if not query:
        return []

    # OCR / CESMM print ``D 549.2``; compact that before the token regexes
    # so a spaced code extracts as ``d549.2`` (WAVE 2 B5). The original
    # fences still apply to the collapsed string — a typo like
    # ``specif8cation`` is unchanged.
    query = normalize_cesmm_item_codes(query)

    found: Set[str] = set()

    # 1. Quoted phrases (preserve exact content).
    for m in _QUOTED_RE.finditer(query):
        phrase = (m.group(1) or m.group(2) or "").strip()
        if phrase and len(phrase) >= 3:
            found.add(phrase.lower())

    # 2. Code-shaped tokens (hyphen/dotted/dashed uppercase codes).
    for m in _CODE_TOKEN_RE.finditer(query):
        token = m.group(0).strip("-.:/")
        if len(token) >= 4:
            found.add(token.lower())

    # 3. Labeled references: "VO Ref 31", "PRC-501", "RFI 12-A", etc.
    for m in _LABELED_REF_FULL_RE.finditer(query):
        label = m.group("label")
        # The captured code may have trailing punctuation; strip it.
        code = m.group("code").strip("-.:,;")
        # A genuine reference code carries a digit (VO 99, Clause 13.1,
        # PRC-501). Several labels ("Contract", "Spec", "Package", ...) are
        # also ordinary English words, so a label followed by a digit-less
        # word ("contract cover", "specification") is prose — NOT a reference.
        # Without this guard those false identifiers earned the +2.0 retrieval
        # bonus and flooded the top-K with boilerplate, so grounded chat
        # answered "I cannot find" for broad questions (2026-06-30 pilot).
        # ...and it must not be a typo'd English word. This rule cheerfully
        # split "specif8cation" into label "spec" + code "if8cation", which
        # carries a digit and so passed the check above (live 2026-08-02).
        if (
            code
            and any(ch.isdigit() for ch in code)
            and not _is_misspelled_word(code)
        ):
            found.add(f"{label.lower()} {code.lower()}")
            found.add(code.lower())

    # 4. Standalone alphanumeric codes containing digits.
    for m in _ALPHANUMERIC_RE.finditer(query):
        token = m.group(0).strip("-.:,;")
        # A pure number with a decimal point is a QUANTITY, not a reference
        # code. Live find 2026-08-15 (F21): a costing request carrying
        # measured quantities ("1947.87 square metres ... 2342.20 metres")
        # had both decimals extracted as identifiers; no chunk contains
        # them, so the exact-reference gate short-circuited every grounded
        # costing question with "could not confirm this reference".
        # Letterless dot/comma-separated digits are never document codes;
        # hyphenated digit pairs (drawing/sheet refs like 054-0009) keep
        # matching. A decimal minus a number (18.4-16) is leftover L7
        # arithmetic, not a sheet ref — that token used to fire the
        # RAG-miss short-circuit ("could not confirm this reference")
        # before sympy_reasoning ever ran.
        if re.fullmatch(r"\d+[.,]\d+", token):
            continue
        if re.fullmatch(r"\d+[.,]\d+[-+*/]\d+(?:[.,]\d+)?", token):
            continue
        if len(token) >= 5 and not _is_prose_compound(token):
            found.add(token.lower())

    # Filter out trivial stopwords, very short tokens, and measurement units
    # (a spec unit like "kg/cm2" is not a reference code — see _looks_like_unit).
    result = [
        t for t in found
        if len(t) >= 2 and t not in _STOPWORDS and not _looks_like_unit(t)
    ]
    # Prefer longer, more specific identifiers first.
    result.sort(key=lambda t: (-len(t), t))
    return result

# --- donor app/core/rag/retriever.py:L347-L367 (filename_matches_named_contracts)
def filename_matches_named_contracts(
    filename: str,
    named_ids: List[str],
    *,
    chunk_text: str = "",
) -> bool:
    """True when this document belongs to a contract the query named.

    The upload filename is the authority — live corpus contract numbers
    live there. An unresolved filename falls back to a *contiguous* id in
    chunk text. Token-soup matching ('dd' + '2023' + '118' scattered) is
    rejected: a DD-2022 Conditions of Contract chunk can contain those
    tokens as a prefix, a date, and a clause number.
    """
    if not named_ids:
        return True
    name_l = (filename or "").lower()
    if name_l:
        return any(cid in name_l for cid in named_ids)
    text_l = (chunk_text or "").lower()
    return any(cid in text_l for cid in named_ids)

# --- donor app/core/rag/retriever.py:L1662-L1667 (query_asks_for_accepted_contract_amount)
def query_asks_for_accepted_contract_amount(query: str) -> bool:
    """True for a filled Accepted Contract Amount ask, not a definition."""
    q = query or ""
    if _DEFINITION_QUESTION_RE.search(q):
        return False
    return bool(_ACA_ASK_RE.search(_normalize_retrieval_ws(q)))

# --- donor app/core/rag/retriever.py:L2794-L2827 (particulars_row_answers_asked_label)
def particulars_row_answers_asked_label(query: str, text: str) -> bool:
    """True when a filled row's KEY is the particular the ask names.

    The unnamed election used to lock the pool to the first filled
    particulars row of any kind. A filled Accepted Contract Amount window
    from another package then stole A3 (Time for Completion), the same
    way a glossary definition used to steal A9 before the role-identity
    ask was recognised.

    #496 required label overlap on the chunk body. That still elects a
    mixed window whose TfC / Delay Damages *key* is unfilled. Live
    d7a4ca8 A3/A5: DD-2022-175 won, Volume 4 ``548 days`` and Sub-Clause
    8.8 stayed in the pool, and DD-2023-118's 852-day / 0.1% rows were
    fenced out. The asked label's own value must be filled.

    When the ask has no named field (a bare "Contract Data" lookup), the
    previous body-overlap test stands so we do not empty a pool we have
    no opinion about.
    """
    phrases = _asked_particular_key_phrases(query)
    if phrases:
        want_whole_tfc = (
            "time for completion" in phrases
            and query_asks_for_time_for_completion(query)
        )
        for key, _val in filled_particulars_rows(text):
            key_l = key.lower()
            if not any(p in key_l for p in phrases):
                continue
            if want_whole_tfc and not _tfc_row_is_whole_works(key, text):
                continue
            return True
        return False
    return _cd_label_bonus(_significant_terms(query), text) > 0.0

# --- donor app/core/rag/retriever.py:L2869-L2884 (query_asks_for_delay_damages_rate)
def query_asks_for_delay_damages_rate(query: str) -> bool:
    """True for a whole-works Delay Damages *rate* ask (live A5).

    E1 ("calculate … in SAR") stays on the monetary-base reservation.
    An ask that names the maximum / cap is not this class.
    """
    q = query or ""
    if not q or _DEFINITION_QUESTION_RE.search(q):
        return False
    if query_needs_a_monetary_base(q):
        return False
    if not re.search(r"(?i)(?:delay|liquidated)\s+damages", q):
        return False
    if re.search(r"(?i)\b(?:maximum|max(?:imum)?\s+amount|capped?)\b", q):
        return False
    return True

# --- donor app/core/rag/retriever.py:L2887-L2902 (query_asks_delay_damages_daily_amount)
def query_asks_delay_damages_daily_amount(query: str) -> bool:
    """True for E1 (calculate … delay damages … in SAR), not A5 rate lookup.

    Reuses the monetary-base ask class so A5 stays a particular lookup
    and this path stays compose-only. Twin of
    ``construction_formulas_commercial.query_asks_delay_damages_daily_amount``.

    Wave-1 A2 ("Accepted Contract Amount including VAT") has no
    delay-damages token, so it stays off this path. A combined
    "calculate delay damages … including VAT" remains E1 — leftover
    E1 after #523 must not be stolen back onto the A2 particular.
    """
    q = query or ""
    if not q or not _DELAY_RATE_KEY_RE.search(q):
        return False
    return query_needs_a_monetary_base(q)

# --- donor app/core/rag/retriever.py:L3208-L3212 (query_asks_for_aca_including_vat)
def query_asks_for_aca_including_vat(query: str) -> bool:
    """True for A2 (including VAT), not A1 excluding or a definition."""
    if not query_asks_for_accepted_contract_amount(query):
        return False
    return bool(_INCLUDING_VAT_RE.search(query or ""))

# --- donor app/core/rag/retriever.py:L5220-L5237 (extract_asked_cesmm_codes)
def extract_asked_cesmm_codes(query: str) -> List[str]:
    """Compact CESMM item codes the ask names (``d529.3``, ``d549.2``)."""
    out: List[str] = []
    seen: Set[str] = set()
    blob = normalize_cesmm_item_codes(query or "")
    for ident in extract_query_identifiers(blob):
        compact = normalize_cesmm_item_codes(ident).lower()
        if not _CESMM_COMPACT_ITEM_RE.fullmatch(compact):
            continue
        if compact not in seen:
            seen.add(compact)
            out.append(compact)
    for match in _CESMM_IN_TEXT_RE.finditer(blob):
        compact = f"{match.group(1)}{match.group(2)}".lower()
        if compact not in seen:
            seen.add(compact)
            out.append(compact)
    return out

# --- donor app/core/rag/retriever.py:L5240-L5267 (query_asks_for_boq_item_amount)
def query_asks_for_boq_item_amount(query: str) -> bool:
    """True for G4 (total amount of a named CESMM / BOQ item).

    A2 (Accepted Contract Amount), A5 (Delay Damages rate) and E1
    (calculate … in SAR) stay off this path. A unit-rate-only ask
    (WAVE 2 B5 without ``amount``) is not this class — the Rate
    column can still be a number when Amount is Rate Only.
    """
    q = (query or "").strip()
    if not q or _DEFINITION_QUESTION_RE.search(q):
        return False
    if query_asks_for_accepted_contract_amount(q):
        return False
    # E1 (calculate delay damages … in SAR) is rate × ACA compose,
    # not a CESMM unit-rate / amount quote. Check the daily-ask
    # class first so a monetary-base regex drift cannot open the
    # priced fence and refuse-close leftover E1.
    if query_asks_delay_damages_daily_amount(q):
        return False
    if query_asks_for_delay_damages_rate(q) or query_needs_a_monetary_base(q):
        return False
    if _UNIT_RATE_ONLY_ASK_RE.search(q) and not re.search(
        r"(?i)\b(?:total\s+)?amount\b", q,
    ):
        return False
    if not _ITEM_AMOUNT_ASK_RE.search(q):
        return False
    return bool(extract_asked_cesmm_codes(q))

# --- donor app/core/rag/retriever.py:L5315-L5333 (chunk_states_rate_only_item)
def chunk_states_rate_only_item(text: str, codes: List[str]) -> bool:
    """True when the asked CESMM row's Amount is Rate Only.

    A priced lookalike on the same page (D549.2 / D599.5) and an
    Excluded culvert that only shares the description are not this.
    A window that already prints qty × rate = amount is priced, even
    when a neighbor or page note says Rate Only (live WAVE 2 B5).
    Does not invent: the excerpt itself must already say Rate Only
    on the asked item's row, with no priced triple in that window.
    """
    if not codes or not _RATE_ONLY_RE.search(text or ""):
        return False
    for code in codes:
        for window in _cesmm_row_windows(text, code):
            if _RATE_ONLY_RE.search(window) and not _parse_priced_cesmm_window(
                window, code,
            ):
                return True
    return False

# --- donor app/core/rag/retriever.py:L5336-L5344 (chunk_states_priced_item)
def chunk_states_priced_item(text: str, codes: List[str]) -> bool:
    """True when the asked CESMM row already prints qty × rate = amount."""
    if not codes or not text:
        return False
    for code in codes:
        for window in _cesmm_row_windows(text, code):
            if _parse_priced_cesmm_window(window, code):
                return True
    return False

# --- donor app/core/rag/retriever.py:L5622-L5648 (query_asks_for_part_summary_total)
def query_asks_for_part_summary_total(query: str) -> bool:
    """True for B3 (Part Summary / page total of a named bill page).

    B4/B5 named-CESMM amounts stay on the priced-row path. A2 / E1
    monetary particulars are not this.
    """
    q = (query or "").strip()
    if not q or _DEFINITION_QUESTION_RE.search(q):
        return False
    if query_asks_for_accepted_contract_amount(q):
        return False
    if query_asks_delay_damages_daily_amount(q):
        return False
    if query_asks_for_delay_damages_rate(q) or query_needs_a_monetary_base(q):
        return False
    if query_asks_for_boq_item_amount(q):
        return False
    refs = extract_asked_boq_page_refs(q)
    if not refs:
        return False
    if _PART_SUMMARY_ASK_RE.search(q):
        return True
    return bool(
        re.search(r"(?i)\btotal\b", q)
        and re.search(r"(?i)\bpage\b", q)
        and _PART_SUMMARY_BILL_RE.search(q)
    )

# --- donor app/core/rag/retriever.py:L3046-L3078 (chunk_answers_asked_particular)
def chunk_answers_asked_particular(query: str, text: str) -> bool:
    """Election / reservation predicate for a particulars-shaped ask.

    Prefixed filled rows keep today's behaviour (A3/A6/A2 year-lock).
    After #501, A5/A9 also accept an unprefixed scanned rate /
    Engineer appointment so the year-lock fence cannot drop the
    chunk that actually answers.
    """
    if delay_damages_rate_rescue_enabled() and query_asks_for_delay_damages_rate(query):
        if chunk_states_delay_damages_rate(text):
            return True
    if delay_damages_daily_rescue_enabled() and query_asks_delay_damages_daily_amount(query):
        if (
            chunk_states_delay_damages_rate(text)
            or chunk_states_accepted_contract_amount(text)
        ):
            return True
    if engineer_identity_rescue_enabled() and query_asks_who_the_engineer_is(query):
        if chunk_states_engineer_identity(text):
            return True
    if aca_including_vat_rescue_enabled() and query_asks_for_aca_including_vat(query):
        if chunk_states_aca_including_vat(text):
            return True
    if time_for_completion_rescue_enabled() and query_asks_for_time_for_completion(query):
        if chunk_states_time_for_completion(text):
            return True
    if dnp_rescue_enabled() and query_asks_for_defects_notification_period(query):
        if chunk_states_defects_notification_period(text):
            return True
    return (
        is_contract_data_particulars_row(text)
        and particulars_row_answers_asked_label(query, text)
    )

# --- donor app/core/rag/retriever.py:L386-L475 (elect_answer_bearing_contract)
def elect_answer_bearing_contract(
    query: str,
    ranked_docs: Iterable[Tuple[str, str]],
) -> Optional[str]:
    """Which contract owns an UNNAMED answer, decided by evidence not by rank.

    ``ranked_docs`` is ``(filename, chunk_text)`` in descending final-score
    order. It may be a lazy iterable: nothing is consumed for a question that
    wants no particular. When the ask is particulars-shaped the walk reads
    every candidate so a later-year filled row can beat an earlier-year
    filled row that happened to rank first (live A3/A5 on d7a4ca8).
    Returns the winning PREFIX-YEAR-SEQ, or None to leave the choice to
    arrival order (today's behaviour).

    WHY THIS EXISTS. The unnamed fence locks onto the first candidate that
    carries a contract id and drops every other id, so the top-ranked chunk
    does not merely outrank the rest — it DELETES the other contract from the
    result set. On the live Master Corpus that is decided by whichever chunk
    happens to sort first, and wave-1 measured both outcomes on one corpus in
    one session: A2 and A6 passed because a DD-2023-118 Contract Data row
    sorted first, while A5 and A9 failed because a DD-2022-175 Conditions of
    Contract clause did — and once it had, the DD-2023-118 row holding the
    answer could not appear at any rank.

    A General Conditions clause or a defined-term glossary entry is not an
    answer to "what is the rate" or "who is the Engineer"; it is a pointer to
    the row that holds it. So when the question asks for a kind of answer and
    the pool contains one, the contract that owns the best-ranked chunk OF
    THAT KIND wins the pool — a pointer from another contract cannot take it
    away.

    When TWO contracts both own that kind of answer (both state a Time for
    Completion, both state a Delay Damages rate), first-in-rank is still
    arrival order. The newer PREFIX-YEAR-SEQ wins: it is the later executed
    package. Naming the older id still fail-closes onto that year.

    Each ask shape brings its own idea of what an answer looks like, because
    the wrong-year chunk that wins is different every time:

    * a filled Contract Data particulars row, for a particular or a numbered
      contract Schedule (wave-1 A3/A5/A9, wave-2 G1);
    * a chunk of a bill of quantities, for measured scope (wave-2 F1, whose
      three citations were all another year's Conditions of Contract prose
      describing the demolition scope in words).

    An ask that matches no shape returns None and keeps arrival order, so
    this can never reorder a corpus it has no opinion about.

    This complements the named-id fence (#443) rather than re-implementing
    it: a question that names its contract never reaches here.
    """
    # (does the ask want this kind of answer?, is this chunk that answer?)
    # Built here, not at module scope: both halves are defined further down.
    kinds = [
        (query_asks_for_contract_particulars,
         lambda _name, text: chunk_answers_asked_particular(query, text)),
        (query_asks_for_boq_scope,
         lambda name, _text: document_is_a_bill_of_quantities(name)),
        (query_asks_for_boq_item_amount,
         lambda _name, text: (
             chunk_states_priced_item(
                 text, extract_asked_cesmm_codes(query),
             )
             or chunk_states_rate_only_item(
                 text, extract_asked_cesmm_codes(query),
             )
         )),
        (query_asks_for_part_summary_total,
         lambda _name, text: chunk_states_part_summary_total(
             text, extract_asked_boq_page_refs(query),
         )),
    ]
    active = [is_answer for asks, is_answer in kinds if asks(query)]
    if not active:
        return None
    found: List[str] = []
    seen: Set[str] = set()
    for filename, text in ranked_docs:
        if not any(is_answer(filename, text) for is_answer in active):
            continue
        ids = extract_contract_doc_ids(filename or "")
        if not ids:
            continue
        cid = ids[0]
        if cid not in seen:
            seen.add(cid)
            found.append(cid)
    if not found:
        return None
    return max(found, key=_contract_id_recency)

# --- donor app/core/rag/coverage_honesty.py (whole module)
"""Coverage honesty line + partial-index absence phrasing.

Every answer that knows its project must carry ``N of M project documents
indexed`` with live counts (or an explicit fixture tuple in tests). Below
100% the model is not allowed to say a clause ``does not exist`` or that
there is ``no such clause`` — those phrases claim a complete search of a
corpus that is still being ingested. Rewrite them to
``not found in the N indexed``.

The 2,935 / 6,206 pair used in tests is the historical coverage fixture,
not a claim about live Neon.
"""


import logging
import re

logger = logging.getLogger(__name__)

COVERAGE_LINE_TEMPLATE = "{n} of {m} project documents indexed"
NOT_FOUND_IN_INDEXED = "not found in the {n} indexed"

# Phrases that assert a complete search. Forbidden on a partial index.
FORBIDDEN_ABSENCE_PHRASES: tuple[str, ...] = (
    "does not exist",
    "no such clause",
)

_COVERAGE_LINE_RE = re.compile(
    r"^\d+ of \d+ project documents indexed\s*$",
    re.MULTILINE,
)
_FORBIDDEN_RE = re.compile(
    r"does not exist|no such clause",
    re.IGNORECASE,
)


def format_coverage_line(indexed: int, total: int) -> str:
    return COVERAGE_LINE_TEMPLATE.format(n=int(indexed), m=int(total))


def format_not_found(indexed: int) -> str:
    return NOT_FOUND_IN_INDEXED.format(n=int(indexed))


def is_partial(indexed: int, total: int) -> bool:
    return int(total) > 0 and int(indexed) < int(total)


def rewrite_forbidden_absence_claims(text: str, indexed: int, total: int) -> str:
    """Replace complete-search claims when coverage is below 100%."""
    if not is_partial(indexed, total):
        return text
    replacement = format_not_found(indexed)
    return _FORBIDDEN_RE.sub(replacement, text or "")


def ensure_coverage_line(text: str, indexed: int, total: int) -> str:
    """Append the honesty line once. Does not invent counts."""
    line = format_coverage_line(indexed, total)
    body = text or ""
    if _COVERAGE_LINE_RE.search(body) or line in body:
        return body
    if body and not body.endswith("\n"):
        body += "\n"
    return body + line + "\n"


def live_coverage(project_id: str) -> Optional[tuple[int, int]]:
    """Indexed-doc count and project-doc count. None when we cannot tell.

    N = documents that have at least one RAG chunk (``count_by_doc``).
    M = ``count_documents`` for the same project. Read-only; does not
    write the ingest path.
    """
    if not (project_id or "").strip():
        return None
    try:
        from app.core.projects import count_documents
        from app.core.rag.vector_store import get_store

        total = int(count_documents(project_id) or 0)
        by_doc = get_store().count_by_doc(project_id) or {}
        indexed = sum(1 for n in by_doc.values() if int(n or 0) > 0)
        return indexed, total
    except Exception:  # honesty must not break an answer
        logger.warning(
            "live coverage lookup failed for project_id=%r", project_id, exc_info=True
        )
        return None


def apply_coverage_honesty(
    text: str,
    *,
    project_id: str | None = None,
    coverage: tuple[int, int] | None = None,
) -> str:
    """Rewrite + stamp the coverage line when counts are known.

    ``coverage`` is the fixture/override pair ``(indexed, total)``. When
    omitted, live counts are read for ``project_id``. No project and no
    fixture → the text is unchanged (tests of other gates stay stable).
    """
    counts = coverage
    if counts is None and project_id:
        counts = live_coverage(project_id)
    if counts is None:
        return text
    indexed, total = int(counts[0]), int(counts[1])
    out = rewrite_forbidden_absence_claims(text, indexed, total)
    return ensure_coverage_line(out, indexed, total)


# ---------------------------------------------------------------------------
# Store adapter
# ---------------------------------------------------------------------------
from app.core.universal_base import UniversalBlock


def _envelope(status, result=None, error=None, detail=None):
    return {
        "block_id": "contract_retrieval",
        "status": status,
        "result": result,
        "error": error,
        "detail": detail,
    }


class ContractRetrievalBlock(UniversalBlock):
    """Construction-contract retrieval machinery, ported from The_Fork.

    Real donor code (verbatim line slices from app/core/rag/retriever.py,
    app/core/contract_data_chunks.py, app/core/rag/vector_store.py and
    app/core/rag/coverage_honesty.py). The embedder/vector-store composition
    of retrieve() is not ported; this block carries the named-contract fence,
    the answer-bearing-contract election and the partial-index disclosure
    contract, and the platform's vector search stays the platform's.
    """

    name = "contract_retrieval"
    version = "1.0.0"
    description = (
        "real (clone of The_Fork app/core/rag/retriever.py + "
        "app/core/rag/coverage_honesty.py + app/core/contract_data_chunks.py): "
        "named-contract fencing (extract_contract_doc_ids / "
        "filename_matches_named_contracts, fail closed to empty) and the "
        "answer-bearing-contract election (elect_answer_bearing_contract with "
        "its full rescue-predicate closure), plus the coverage-honesty rule: "
        "on a partial index the model may not say 'does not exist', only "
        "'not found in the N indexed'. Retrieval corpus/embedder not ported."
    )
    layer = 3
    tags = ["rag", "retrieval", "contract", "coverage-honesty", "construction", "the-fork"]
    requires = []

    default_config = {}

    ui_schema = {
        "input": {
            "type": "json",
            "placeholder": '{"action": "elect", "query": "What are the Delay Damages for the whole of the Works?", "ranked_docs": [["DD-2022-175 ....pdf", "Sub-Clause 8.8 ..."], ["DD-2023-118 ....pdf", "8.8 Delay Damages ... 0.1% ..."]]}',
            "multiline": True,
        },
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "result", "type": "json", "label": "Result"}]},
    }

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "")).lower()
        try:
            if action == "elect":
                return self._elect(payload)
            if action == "fence":
                return self._fence(payload)
            if action == "coverage":
                return self._coverage(payload)
            if action == "contract_ids":
                return _envelope(
                    "ok",
                    {"ids": extract_contract_doc_ids(str(payload.get("text") or ""))},
                )
            return _envelope(
                "error",
                error=f"unknown action: {action or '(none)'}",
                detail={"known": ["elect", "fence", "coverage", "contract_ids"]},
            )
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=f"{type(exc).__name__}: {exc}")

    def _elect(self, payload):
        query = str(payload.get("query") or "")
        ranked_docs = payload.get("ranked_docs") or []
        if not query.strip():
            return _envelope("refused", error="an election needs a query")
        if not ranked_docs:
            return _envelope(
                "refused",
                error="an election needs ranked (filename, chunk_text) pairs; "
                "an empty pool cannot elect a contract",
            )
        winner = elect_answer_bearing_contract(
            query, [(str(n), str(t)) for n, t in ranked_docs]
        )
        return _envelope(
            "ok",
            {
                "elected_contract": winner,
                "note": (
                    "None means the ask matched no answer shape: arrival order "
                    "still decides, the election never reorders a corpus it "
                    "has no opinion about."
                    if winner is None
                    else None
                ),
            },
        )

    def _fence(self, payload):
        query = str(payload.get("query") or "")
        docs = payload.get("docs") or []
        if not docs:
            return _envelope("refused", error="a fence needs a doc pool to filter")
        named = extract_contract_doc_ids(query)
        kept = [
            d for d in docs
            if filename_matches_named_contracts(
                str(d.get("filename") if isinstance(d, dict) else d),
                named,
                chunk_text=str(d.get("chunk_text", "")) if isinstance(d, dict) else "",
            )
        ]
        if named and not kept:
            # The cross-contract fence is fail-closed: a named id with no
            # matching documents is an empty result, never another year.
            return _envelope(
                "refused",
                error=(
                    f"named contract id(s) {named} matched no document in the "
                    "pool; refusing to fill with another contract's files"
                ),
                detail={"named_ids": named, "pool_size": len(docs)},
            )
        return _envelope("ok", {"named_ids": named, "kept": kept, "dropped": len(docs) - len(kept)})

    def _coverage(self, payload):
        text = str(payload.get("text") or "")
        coverage = payload.get("coverage")
        if not isinstance(coverage, (list, tuple)) or len(coverage) != 2:
            return _envelope(
                "refused",
                error="coverage needs an explicit [indexed, total] pair; live "
                "counts require the donor's project/vector-store stack, which "
                "is not ported",
            )
        out = apply_coverage_honesty(text, coverage=(int(coverage[0]), int(coverage[1])))
        return _envelope(
            "ok",
            {
                "text": out,
                "partial": is_partial(int(coverage[0]), int(coverage[1])),
            },
        )

