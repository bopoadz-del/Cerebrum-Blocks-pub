"""ST-7c: served-text detector — hosting-provider names (word-bounded on both
sides) and <angle-bracket> placeholders in text a block serves."""
from __future__ import annotations

import re

import pytest

PROVIDER = re.compile(r"\b(aws|render|heroku|vercel|netlify|azure)\b", re.IGNORECASE)
PLACEHOLDER = re.compile(r"<[a-z][a-z0-9-]*>")


def served_text_hits(text: str) -> list:
    """(line, kind, match) for provider names and <placeholder> tokens."""
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        hits += [(i, "provider", m.group(0)) for m in PROVIDER.finditer(line)]
        hits += [(i, "placeholder", m.group(0)) for m in PLACEHOLDER.finditer(line)]
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
