"""Translate block: language-code normalisation and the deep_translator call.

Offline. `deep_translator.GoogleTranslator` and `deep_translator.single_detection`
are replaced with recorders, so the block's own code runs unchanged while the
network hop is faked; nothing leaves the process.

tests/blocks/test_translate.py drives only provider="mock" and asserts the
UniversalBlock envelope, so it never reads result["translated"] and never
reaches _normalize_lang or _translate_sync. Each assertion below names a value
TranslateBlock.process computed: the ISO code it resolved a language *name* to,
the text it handed the translator, the detected source it reported back, the
character count, and the refusal for empty input.
"""

from __future__ import annotations

import pytest

from app.blocks.translate import TranslateBlock


class _FakeTranslator:
    """Records how GoogleTranslator was constructed and what it was given."""

    constructions = []
    translations = []
    raises = None
    output = "TRANSLATED"

    def __init__(self, source=None, target=None):
        type(self).constructions.append({"source": source, "target": target})
        self.source = source
        self.target = target

    def translate(self, text):
        type(self).translations.append(text)
        if type(self).raises is not None:
            raise type(self).raises
        return type(self).output


@pytest.fixture
def fake_translator(monkeypatch):
    import deep_translator

    _FakeTranslator.constructions = []
    _FakeTranslator.translations = []
    _FakeTranslator.raises = None
    _FakeTranslator.output = "TRANSLATED"
    detections = []

    def fake_single_detection(text, api_key=None):
        detections.append(text)
        return "de"

    monkeypatch.setattr(deep_translator, "GoogleTranslator", _FakeTranslator)
    monkeypatch.setattr(deep_translator, "single_detection", fake_single_detection)
    _FakeTranslator.detections = detections
    return _FakeTranslator


# -- Refusals ------------------------------------------------------------------


async def test_empty_text_is_refused():
    out = await TranslateBlock().process("", {"target": "es"})

    assert out["status"] == "error"
    assert out["error"] == "Text is required"


async def test_whitespace_only_text_is_refused():
    out = await TranslateBlock().process("   \n\t ", {"target": "es"})

    assert out["status"] == "error"
    assert out["error"] == "Text is required"


# -- The language table --------------------------------------------------------


async def test_languages_operation_returns_the_real_code_table():
    out = await TranslateBlock().process("x", {"operation": "languages"})

    languages = out["languages"]
    assert languages["arabic"] == "ar"
    assert languages["chinese"] == "zh-CN", "not a bare 'zh'"
    assert languages["portuguese"] == "pt"
    assert len(languages) == 20


async def test_language_names_are_normalised_to_iso_codes():
    """'Spanish' and 'German' are resolved through _LANG_CODES, case-folded."""
    out = await TranslateBlock().process(
        "Hello world", {"provider": "mock", "target": "Spanish", "source": "  German "}
    )

    assert out["target_language"] == "es"
    assert out["source_language"] == "de"


async def test_an_unrecognised_language_is_passed_through_lowercased():
    """Unknown names are not refused: they go downstream as-is, lowercased."""
    out = await TranslateBlock().process(
        "Hello", {"provider": "mock", "target": "Esperanto"}
    )

    assert out["target_language"] == "esperanto"


async def test_target_defaults_to_spanish_and_source_to_auto():
    out = await TranslateBlock().process("Hello", {"provider": "mock"})

    assert out["target_language"] == "es"
    assert out["source_language"] == "auto"


async def test_mock_provider_returns_the_input_unchanged_with_its_char_count():
    out = await TranslateBlock().process("Hello world", {"provider": "mock"})

    assert out["original"] == "Hello world"
    assert out["translated"] == "Hello world"
    assert out["char_count"] == 11
    assert out["provider"] == "mock"


async def test_text_may_arrive_in_a_dict_under_text_or_input():
    for key in ("text", "input"):
        out = await TranslateBlock().process({key: "  padded  "}, {"provider": "mock"})
        assert out["original"] == "padded", "input is stripped before translation"


# -- The real deep_translator path ---------------------------------------------


async def test_auto_source_is_detected_and_reported_back(fake_translator):
    fake_translator.output = "Hallo Welt"

    out = await TranslateBlock().process("Hello world", {"target": "german"})

    assert fake_translator.constructions == [{"source": "auto", "target": "de"}]
    assert fake_translator.translations == ["Hello world"]
    assert out["translated"] == "Hallo Welt"
    assert out["original"] == "Hello world"
    assert out["source_language"] == "de", "the detected language, not 'auto'"
    assert out["target_language"] == "de"
    assert out["char_count"] == 11
    assert fake_translator.detections == ["Hello world"]


async def test_detection_reads_at_most_the_first_200_characters(fake_translator):
    text = "a" * 900

    await TranslateBlock().process(text, {"target": "fr"})

    assert len(fake_translator.detections[0]) == 200


async def test_an_explicit_source_skips_detection_entirely(fake_translator):
    fake_translator.output = "Bonjour"

    out = await TranslateBlock().process("Hola", {"source": "spanish", "target": "french"})

    assert fake_translator.detections == [], "no detection call when source is explicit"
    assert fake_translator.constructions == [{"source": "es", "target": "fr"}]
    assert out["source_language"] == "es"
    assert out["translated"] == "Bonjour"


async def test_text_is_truncated_to_5000_chars_before_translation(fake_translator):
    """Only the first 5000 characters are sent - but char_count reports them all.

    Pinning both numbers because they disagree: a 6000-character document comes
    back with char_count=6000 while 1000 characters were silently dropped.
    """
    text = "x" * 6000

    out = await TranslateBlock().process(text, {"target": "es"})

    assert len(fake_translator.translations[0]) == 5000
    assert out["char_count"] == 6000


async def test_translator_failure_is_reported_with_the_resolved_target(fake_translator):
    fake_translator.raises = RuntimeError("translate quota exceeded")

    out = await TranslateBlock().process("Hello", {"target": "French"})

    assert out["status"] == "error"
    assert "translate quota exceeded" in out["error"]
    assert out["target"] == "fr", "the resolved code, so the caller can retry"


async def test_detection_failure_degrades_to_unknown_not_to_an_error(
    fake_translator, monkeypatch
):
    import deep_translator

    def boom(text, api_key=None):
        raise RuntimeError("detector offline")

    monkeypatch.setattr(deep_translator, "single_detection", boom)
    fake_translator.output = "Hola"

    out = await TranslateBlock().process("Hello", {"target": "es"})

    assert out["status"] == "success"
    assert out["source_language"] == "unknown"
    assert out["translated"] == "Hola", "translation still happens without detection"
