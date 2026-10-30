"""ST-7c: served-text detector — hosting-provider names (word-bounded on both
sides) and <angle-bracket> placeholders in text a block serves.

#26 extension: TODO markers (case-insensitive, whole word: "todolist" is not a
hit), "lorem ipsum" filler (case-insensitive) and empty / whitespace-only text."""
from __future__ import annotations

import re

import pytest

PROVIDER = re.compile(r"\b(aws|render|heroku|vercel|netlify|azure)\b", re.IGNORECASE)
PLACEHOLDER = re.compile(r"<[a-z][a-z0-9-]*>")
TODO = re.compile(r"\btodo\b", re.IGNORECASE)
LOREM = re.compile(r"\blorem\s+ipsum\b", re.IGNORECASE)


def served_text_hits(text: str) -> list:
    """(line, kind, match) for provider names, <placeholder> tokens, TODO
    markers and lorem ipsum filler; empty or whitespace-only text is one
    (1, "empty", "") hit."""
    if not text.strip():
        return [(1, "empty", "")]
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        hits += [(i, "provider", m.group(0)) for m in PROVIDER.finditer(line)]
        hits += [(i, "placeholder", m.group(0)) for m in PLACEHOLDER.finditer(line)]
        hits += [(i, "todo", m.group(0)) for m in TODO.finditer(line)]
        hits += [(i, "lorem", m.group(0)) for m in LOREM.finditer(line)]
    return hits


@pytest.mark.parametrize("text, expected", [
    ("# Then: the deploy workflow ships the pushed commit\n", []),
    ("# Then: the deploy workflow (deploy-aws) ships the pushed commit\n", [(1, "provider", "aws")]),
    ("ok\nDeploy on Render.\n", [(2, "provider", "Render")]),
    ("git pull origin main\n", []),
    ("git clone <store-repo-url>\n", [(1, "placeholder", "<store-repo-url>")]),
    ("awsome lambda rendering\n", []),
    ("Push to Heroku\n", [(1, "provider", "Heroku")]),
    ("vercel deploy\n", [(1, "provider", "vercel")]),
    ("netlify build\n", [(1, "provider", "netlify")]),
    ("an Azure app\n", [(1, "provider", "Azure")]),
    ("on aws today\n", [(1, "provider", "aws")]),
])
def test_served_text_hits_two_inputs(text, expected):
    assert served_text_hits(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("jaws prerender\n", []),
    ("jaws on aws\n", [(1, "provider", "aws")]),
    ("prerender then render\n", [(1, "provider", "render")]),
])
def test_provider_leading_word_boundary(text, expected):
    assert served_text_hits(text) == expected


@pytest.mark.parametrize("text", [
    "a <> b\n",              # L2: empty brackets are not a placeholder
    "if x < y and y > z\n",  # L2: comparison operators are not a placeholder
    "<store repo url>\n",    # L2: spaces are not a placeholder token
    "<1st-url>\n",           # L3: leading digit
    "<-url>\n",              # L3: leading dash
    "<Store-Repo-URL>\n",    # L4: placeholders are lower-case only
    "<B>bold</B>\n",         # L4: an upper-case tag is not a placeholder
])
def test_placeholder_negative_inputs(text):
    assert served_text_hits(text) == []


@pytest.mark.parametrize("text, expected", [
    ("deploy on aws or heroku\n", [(1, "provider", "aws"), (1, "provider", "heroku")]),
    ("Render, then Netlify\n", [(1, "provider", "Render"), (1, "provider", "Netlify")]),
    ("push <repo-url> to vercel and <branch>\n",
     [(1, "provider", "vercel"), (1, "placeholder", "<repo-url>"), (1, "placeholder", "<branch>")]),
])
def test_every_hit_on_one_line_reports(text, expected):
    assert served_text_hits(text) == expected


# ---- #26 extension (G6 #28 survivors): TODO, lorem ipsum, empty text ----
@pytest.mark.parametrize("text, expected", [
    ("TODO: describe this block\n", [(1, "todo", "TODO")]),
    ("ok\nfill in later (todo)\n", [(2, "todo", "todo")]),
    ("Returns a ToDo list\n", [(1, "todo", "ToDo")]),
    ("Returns a todolist and its todos\n", []),  # whole word only
    ("Returns a task list\n", []),
])
def test_todo_marker_is_flagged_as_a_word(text, expected):
    assert served_text_hits(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("Lorem ipsum dolor sit amet\n", [(1, "lorem", "Lorem ipsum")]),
    ("x\nsee LOREM  IPSUM text\n", [(2, "lorem", "LOREM  IPSUM")]),
    ("lorem alone, ipsum alone\n", []),
    ("Scores a lease clause\n", []),
])
def test_lorem_ipsum_is_flagged(text, expected):
    assert served_text_hits(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("", [(1, "empty", "")]),
    ("   ", [(1, "empty", "")]),
    (" \n\t\n", [(1, "empty", "")]),
    (" a\n", []),
])
def test_empty_or_whitespace_text_is_flagged(text, expected):
    assert served_text_hits(text) == expected


# ---- word boundaries pinned on both sides (G6 #26 repair) ----
@pytest.mark.parametrize("text, expected", [
    ("mytodo list\n", []),            # leading boundary
    ("todos and a todolist\n", []),   # trailing boundary
    ("my todo list\n", [(1, "todo", "todo")]),
    ("dolorem ipsum\n", []),          # leading boundary
    ("lorem ipsumx\n", []),           # trailing boundary
    ("do lorem ipsum.\n", [(1, "lorem", "lorem ipsum")]),
])
def test_todo_and_lorem_word_boundaries_both_sides(text, expected):
    assert served_text_hits(text) == expected
