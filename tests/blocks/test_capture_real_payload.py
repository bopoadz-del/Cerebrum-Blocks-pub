"""CaptureBlock.process — entry-point coverage with real pixels on disk.

Why this file exists
--------------------
``tests/blocks/test_capture.py`` drives ``execute`` and asserts only the
UniversalBlock envelope keys, which ``TypedBlock.execute`` supplies whatever
``process`` returned, so the control-delete in ``scripts/certify_block.py``
gutted ``CaptureBlock.process`` and that suite stayed GREEN.

Every assertion below is on something ``process`` had to compute: the action
router's rejection string, the fabricated demo record it emits when no image
resolves, the base64 it built by reading a real PNG off disk, the mapping of a
markdown-fenced provider JSON into the capture record's own field names, the
confidence it averaged out of per-word OCR scores, and the vector-store hits it
unpacked.

Fixture note: the image is a PIL PNG written to disk in-test (precedent:
``tests/test_image_detection.py``); the Kimi Vision / structuring envelopes and
the vector-store responses are doubled in-test. No network, no API key, no
tesseract binary.
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest
from PIL import Image, ImageDraw

from app.blocks.capture import CaptureBlock


MOONSHOT_URL = "https://api.moonshot.ai/v1/chat/completions"
CHROMA_ADD = "http://localhost:8001/api/v1/collections/add"
CHROMA_QUERY = "http://localhost:8001/api/v1/collections/query"


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=self)


def _double_http(monkeypatch, routes: dict):
    """Route every httpx POST the block makes. Returns the request log.

    ``capture.py`` imports httpx inside each method, so the double has to be
    installed on the httpx module itself; monkeypatch removes it afterwards.
    """
    calls: list[dict] = []

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, headers=None, json=None):
            calls.append({"url": url, "headers": headers or {}, "body": json or {}})
            if url not in routes:
                raise AssertionError(f"unrouted POST to {url}")
            return routes[url]

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    return calls


def _completion(content: str) -> _FakeResponse:
    return _FakeResponse(
        200,
        {
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": {"total_tokens": 88},
        },
    )


@pytest.fixture
def block(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    for name in ("KIMI_API_KEY", "MOONSHOT_API_KEY", "KIMI_MODEL",
                 "MOONSHOT_MODEL", "KIMI_BASE_URL", "MOONSHOT_BASE_URL",
                 "KIMI_VISION_MODEL"):
        monkeypatch.delenv(name, raising=False)
    return CaptureBlock()


@pytest.fixture
def site_photo(tmp_path):
    """A real PNG on disk with real ink on it."""
    img = Image.new("RGB", (400, 100), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((10, 30), "CONCRETE POUR L3 GRID B-C", fill="black")
    path = tmp_path / "site_photo.png"
    img.save(path)
    return path


# ── the action router ──────────────────────────────────────────────────────


async def test_unknown_action_is_refused_by_name(block):
    result = await block.process({"file_path": "ignored"}, {"action": "sculpt"})

    assert result["status"] == "error"
    assert result["error"] == "Unknown action: sculpt"


async def test_ocr_action_without_a_resolvable_image_is_refused(block):
    result = await block.process({"note": "no image here"}, {"action": "ocr"})

    assert result["status"] == "error"
    assert result["error"] == "No valid image provided"


async def test_capture_without_an_image_returns_a_fabricated_demo_record(block):
    """FINDING, pinned: a missing image is reported as status=success.

    The block answers with hard-coded demo content rather than an error, so a
    caller that only checks ``status`` cannot tell a real capture from this.
    """
    result = await block.process({"note": "no image here"}, {"action": "capture"})

    assert result["status"] == "success"
    assert result["mode"] == "demo"
    assert result["ocr_text"] == (
        "Demo: Site inspection photo showing concrete pour in progress."
    )
    assert result["structured"]["activity"] == "Concrete Pour"
    assert result["structured"]["location"] == "Level 3, Grid B-C/4-5"
    assert result["structured"]["items"] == ["Concrete C30", "Rebar mesh", "Formwork"]
    assert result["confidence"] == 0.85


# ── the vision pipeline ────────────────────────────────────────────────────


async def test_vision_json_is_mapped_into_the_capture_record(
    block, site_photo, monkeypatch
):
    monkeypatch.setenv("KIMI_API_KEY", "not-a-real-key")
    vision_json = {
        "raw_text": "POUR CARD 41\nC30/20 - 120 m3",
        "clean_text": "Pour card 41. C30/20, 120 m3.",
        "summary": "A concrete pour card for level 3.",
        "entities": [
            {"type": "amount", "value": "120 m3"},
            {"type": "location", "value": "Level 3"},
        ],
        "tags": ["concrete", "pour", "level-3"],
        "language": "mixed",
        "confidence": 0.88,
    }
    calls = _double_http(
        monkeypatch,
        {
            # the provider replies in a markdown fence — _safe_parse_json must strip it
            MOONSHOT_URL: _completion(
                "```json\n" + json.dumps(vision_json) + "\n```"
            ),
            CHROMA_ADD: _FakeResponse(200, {"ok": True}),
        },
    )

    result = await block.process(
        {"file_path": str(site_photo)},
        {"action": "capture", "capture_id": "cap-7",
         "source": "site-app", "user_id": "eng-12"},
    )

    assert result["status"] == "success"
    assert result["capture_id"] == "cap-7"
    assert result["source"] == "site-app"
    assert result["user_id"] == "eng-12"
    assert result["image_path"] == str(site_photo)

    # Provider fields land under the capture record's own names.
    assert result["raw_text"] == vision_json["raw_text"]
    assert result["clean_text"] == vision_json["clean_text"]
    assert result["summary"] == vision_json["summary"]
    assert result["entities"] == vision_json["entities"]
    assert result["tags"] == ["concrete", "pour", "level-3"]
    assert result["language_detected"] == "mixed", "'language' -> 'language_detected'"
    assert result["ocr_confidence"] == 0.88, "'confidence' -> 'ocr_confidence'"
    assert result["ocr_engine"] == "kimi-vision"
    assert result["timestamp"].startswith("20")

    # The block read the real file and inlined it as a data URI.
    vision_body = calls[0]["body"]
    data_uri = vision_body["messages"][1]["content"][0]["image_url"]["url"]
    assert data_uri.startswith("data:image/png;base64,")
    assert base64.b64decode(data_uri.split(",", 1)[1]) == site_photo.read_bytes()

    # It then stored the cleaned text under the capture id.
    assert result["memory_id"] == "cap-7"
    store_body = calls[1]["body"]
    assert store_body["ids"] == ["cap-7"]
    assert store_body["documents"] == [vision_json["clean_text"]]
    assert store_body["collection"] == "cerebrum_captures"
    assert json.loads(store_body["metadatas"][0]["tags"]) == vision_json["tags"]


async def test_vision_provider_failure_is_returned_not_swallowed(
    block, site_photo, monkeypatch
):
    monkeypatch.setenv("KIMI_API_KEY", "not-a-real-key")
    _double_http(monkeypatch, {MOONSHOT_URL: _FakeResponse(429, text="rate limited")})

    result = await block.process(
        {"file_path": str(site_photo)}, {"action": "capture"}
    )

    assert result["status"] == "error"
    assert "429" in result["error"]
    assert "capture_id" not in result


# ── OCR and structuring ────────────────────────────────────────────────────


async def test_ocr_action_averages_per_word_confidence_from_the_real_image(
    block, site_photo, monkeypatch
):
    """Tesseract is doubled; what the block does with its output is not."""
    import pytesseract

    seen: list[dict] = []

    def _fake_image_to_string(img, lang=None, **kwargs):
        seen.append({"mode": img.mode, "size": img.size, "lang": lang})
        return "CONCRETE POUR L3 GRID B-C\n"

    def _fake_image_to_data(img, lang=None, output_type=None, **kwargs):
        return {"conf": [-1, 90, 80, 70, 95, 85]}

    monkeypatch.setattr(pytesseract, "image_to_string", _fake_image_to_string)
    monkeypatch.setattr(pytesseract, "image_to_data", _fake_image_to_data)

    result = await block.process(
        {"file_path": str(site_photo)}, {"action": "ocr", "languages": "ara+eng"}
    )

    assert result["status"] == "success"
    assert result["text"] == "CONCRETE POUR L3 GRID B-C"
    assert result["engine"] == "tesseract"
    assert result["languages"] == "ara+eng"
    assert result["word_count"] == 5
    # (90 + 80 + 70 + 95 + 85) / 5 = 84 -> 0.84; the -1 word is discarded.
    assert result["confidence"] == 0.84

    # The real PNG was opened and greyscaled before it was handed over.
    assert seen == [{"mode": "L", "size": (400, 100), "lang": "ara+eng"}]


async def test_structure_action_truncates_at_max_chars_and_unpacks_the_json(
    block, monkeypatch
):
    monkeypatch.setenv("KIMI_API_KEY", "not-a-real-key")
    structured = {
        "clean_text": "Invoice from ACME Corp for $500 dated 2024-01-15.",
        "summary": "An ACME invoice for $500.",
        "entities": [{"type": "org", "value": "ACME Corp"}],
        "tags": ["invoice", "acme"],
        "language": "en",
    }
    calls = _double_http(
        monkeypatch, {MOONSHOT_URL: _completion(json.dumps(structured))}
    )

    raw = "Invoice from ACME Corp for $500 dated 2024-01-15. " + "PADDING " * 40
    result = await block.process(raw, {"action": "structure", "max_chars": 49})

    assert result["status"] == "success"
    assert result["clean_text"] == structured["clean_text"]
    assert result["summary"] == structured["summary"]
    assert result["entities"] == [{"type": "org", "value": "ACME Corp"}]
    assert result["tags"] == ["invoice", "acme"]
    assert result["language"] == "en"

    # Only the first max_chars characters were sent.
    sent = calls[0]["body"]["messages"][1]["content"]
    assert "Invoice from ACME Corp for $500 dated 2024-01-15." in sent
    assert "PADDING" not in sent


async def test_unparseable_provider_reply_yields_an_empty_structure(
    block, monkeypatch
):
    """_safe_parse_json returns {} rather than raising; the record stays empty."""
    monkeypatch.setenv("KIMI_API_KEY", "not-a-real-key")
    _double_http(monkeypatch, {MOONSHOT_URL: _completion("sorry, I can't do that")})

    result = await block.process("some text", {"action": "structure"})

    assert result == {"status": "success"}


# ── vector search ──────────────────────────────────────────────────────────


async def test_search_action_unpacks_the_vector_store_hits(block, monkeypatch):
    hits = [
        {"id": "cap-7", "document": "Pour card 41. C30/20, 120 m3.", "score": 0.91},
        {"id": "cap-9", "document": "Rebar fixing level 3.", "score": 0.77},
    ]
    calls = _double_http(
        monkeypatch, {CHROMA_QUERY: _FakeResponse(200, {"results": hits})}
    )

    result = await block.process("concrete pour level 3", {"action": "search",
                                                           "n_results": 3})

    assert result["status"] == "success"
    assert result["results"] == hits
    assert [h["id"] for h in result["results"]] == ["cap-7", "cap-9"]

    body = calls[0]["body"]
    assert body["query"] == "concrete pour level 3"
    assert body["n_results"] == 3
    assert body["collection"] == "cerebrum_captures"
