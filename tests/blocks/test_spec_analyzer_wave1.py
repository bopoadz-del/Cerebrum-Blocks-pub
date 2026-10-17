"""Wave 1.4 regression tests — spec_analyzer ports from The_Fork.

Locks the citation-regex fixes: BS EN before BS, ASTM year suffixes,
AS (Australian) and IBC codes, and grade-stopword filtering.
"""

from app.blocks.spec_analyzer import SpecAnalyzerBlock


def _grades(text: str):
    block = SpecAnalyzerBlock()
    # Tuples, NOT frozensets: frozenset iteration order is hash-dependent
    # (varies with PYTHONHASHSEED), which made unpacking flaky.
    return {(g["type"], g["value"]) for g in block._extract_grades(text)}


def test_bs_en_matches_before_bs():
    out = _grades("Concrete per BS EN 1992-1-1 and BS 8500.")
    assert ("bs_en_standard", "1992-1") in out
    assert ("bs_standard", "8500") in out


def test_astm_trailing_year_and_slash_grade():
    out = _grades("Reinforcement to ASTM A615-22 and ASTM A706/A706M.")
    assert ("astm_standard", "A615-22") in out
    assert any(t == "astm_standard" and v.startswith("A706") for t, v in out)


def test_as_and_ibc_codes():
    out = _grades("Design to AS 3600; building per IBC 2021.")
    assert ("as_standard", "3600") in out
    assert ("ibc_standard", "2021") in out


def test_grade_stopwords_do_not_leak():
    out = _grades("The type of concrete shall be verified.")
    # "of" must not surface as a grade value.
    assert not any(t == "grade" and v == "of" for t, v in out)
