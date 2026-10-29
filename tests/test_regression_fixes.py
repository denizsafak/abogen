import pytest
from unittest.mock import patch
from abogen.kokoro_text_normalization import (
    normalize_for_pipeline,
    DEFAULT_APOSTROPHE_CONFIG,
)
from abogen.normalization_settings import build_apostrophe_config, _SETTINGS_DEFAULTS


def normalize(text, overrides=None):
    settings = dict(_SETTINGS_DEFAULTS)
    if overrides:
        settings.update(overrides)

    config = build_apostrophe_config(settings=settings, base=DEFAULT_APOSTROPHE_CONFIG)
    return normalize_for_pipeline(text, config=config, settings=settings)


def test_year_pronunciation():
    # 1925 -> Nineteen Hundred Twenty Five
    normalized = normalize("1925")
    print(f"1925 -> {normalized}")
    assert "nineteen hundred" in normalized.lower()
    assert "five" in normalized.lower()

    # 2025 -> Twenty Twenty Five
    normalized = normalize("2025")
    print(f"2025 -> {normalized}")
    assert "twenty twenty" in normalized.lower()
    assert "five" in normalized.lower()


def test_currency_pronunciation():
    # $1.00 -> One dollar (no zero cents)
    normalized = normalize("$1.00")
    print(f"$1.00 -> {normalized}")
    assert "one dollar" in normalized.lower()
    assert "zero cents" not in normalized.lower()

    # $1.05 -> One dollar and five cents (or comma)
    normalized = normalize("$1.05")
    print(f"$1.05 -> {normalized}")
    assert "one dollar" in normalized.lower()
    assert "five cents" in normalized.lower()


def test_url_pronunciation():
    # https://www.amazon.com -> amazon dot com
    normalized = normalize("https://www.amazon.com")
    print(f"https://www.amazon.com -> {normalized}")
    assert "amazon dot com" in normalized.lower()
    assert "http" not in normalized.lower()
    assert "www" not in normalized.lower()

    # www.google.com -> google dot com
    normalized = normalize("www.google.com")
    print(f"www.google.com -> {normalized}")
    assert "google dot com" in normalized.lower()


def test_roman_numerals_world_war():
    # World War I -> World War One
    normalized = normalize("World War I")
    print(f"World War I -> {normalized}")
    assert "world war one" in normalized.lower()

    # World War II -> World War Two
    normalized = normalize("World War II")
    print(f"World War II -> {normalized}")
    assert "world war two" in normalized.lower()


def test_footnote_removal():
    # A plain digit suffix cannot reliably be identified as a footnote.
    normalized = normalize("Bob is awesome1.")
    print(f"Bob is awesome1. -> {normalized}")
    assert normalized == "Bob is awesome1."

    # Citation needed[1]. -> Citation needed.
    normalized = normalize("Citation needed[1].")
    print(f"Citation needed[1]. -> {normalized}")
    assert "citation needed." in normalized.lower()
    assert "[1]" not in normalized


@pytest.mark.parametrize("mode", ["spacy", "off"])
@pytest.mark.parametrize(
    "text",
    [
        "F1 FP1 Q1 Q2 Q3 CO2 H2O 3D MP3 x86.",
        "word1 awesome1 version2 item23.",
        "H2O2 B2B ISO9001 F1-car model2_rev3.",
    ],
)
def test_footnote_cleanup_preserves_alphanumeric_terms(text, mode):
    assert normalize(text, {"normalization_apostrophe_mode": mode}) == text


@pytest.mark.parametrize("mode", ["spacy", "off"])
@pytest.mark.parametrize("convert_numbers", [True, False])
def test_footnote_cleanup_removes_explicit_markers_only(mode, convert_numbers):
    assert normalize(
        "F1[1] and H2O[23][2]. Evidence[123].",
        {
            "normalization_apostrophe_mode": mode,
            "normalization_numbers": convert_numbers,
        },
    ) == "F1 and H2O. Evidence."


@pytest.mark.parametrize("mode", ["spacy", "off"])
def test_superscript_digits_are_normalized_without_guessing_footnotes(mode):
    # NFKC flattens superscripts before footnote cleanup sees the text.
    assert normalize(
        "Evidence¹ and Evidence²³.", {"normalization_apostrophe_mode": mode}
    ) == "Evidence1 and Evidence23."


@pytest.mark.parametrize("mode", ["spacy", "off"])
def test_footnote_cleanup_disabled_preserves_bracket_markers(mode):
    text = "F1[1] and H2O[23][2]."
    assert normalize(
        text,
        {
            "normalization_apostrophe_mode": mode,
            "normalization_footnotes": False,
            "normalization_numbers": False,
        },
    ) == "F1[1] and H2O[23] [2]."


def test_manual_override_normalization():
    from abogen.entity_analysis import normalize_manual_override_token

    assert normalize_manual_override_token("The") == "the"
    assert normalize_manual_override_token("  A  ") == "a"
    assert normalize_manual_override_token("word") == "word"


def test_paragraph_breaks_and_ellipsis_preserved():
    normalized = normalize("Test. Lorem ipsum...\n\nLorem...\n\nLorem ...")
    assert "\n\n" in normalized
    assert ". . ." not in normalized
    assert "Lorem..." in normalized
