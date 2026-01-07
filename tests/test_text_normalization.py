from __future__ import annotations

import pytest
from unittest.mock import patch

from abogen.kokoro_text_normalization import (
    DEFAULT_APOSTROPHE_CONFIG,
    normalize_for_pipeline,
    normalize_roman_numeral_titles,
)
from abogen.normalization_settings import (
    apply_overrides as apply_normalization_overrides,
    build_apostrophe_config,
    get_runtime_settings,
)
from abogen.spacy_contraction_resolver import resolve_ambiguous_contractions


SPACY_RESOLVER_AVAILABLE = bool(resolve_ambiguous_contractions("It's been a long time."))


def _normalize_text(text: str, *, normalization_overrides: dict[str, object] | None = None) -> str:
    runtime_settings = get_runtime_settings()
    if normalization_overrides:
        runtime_settings = apply_normalization_overrides(runtime_settings, normalization_overrides)
    config = build_apostrophe_config(settings=runtime_settings, base=DEFAULT_APOSTROPHE_CONFIG)
    return normalize_for_pipeline(text, config=config, settings=runtime_settings)


def test_title_abbreviations_are_expanded():
    text = "Dr. Watson met Mr. Holmes and Ms. Hudson."
    normalized = _normalize_text(text)
    assert "Doctor" in normalized
    assert "Mister" in normalized
    assert "Miz" in normalized


def test_suffix_abbreviations_are_expanded_with_case_preserved():
    text = "John Doe Jr. spoke to JANE DOE SR. about the estate."
    normalized = _normalize_text(text)
    assert "John Doe Junior" in normalized
    assert "JANE DOE SENIOR" in normalized


def test_missing_terminal_punctuation_is_added():
    normalized = _normalize_text("Chapter 1")
    assert normalized.endswith(".")


def test_terminal_punctuation_respects_closing_quotes():
    normalized = _normalize_text('"Chapter 1"')
    compact = normalized.replace(" ", "")
    assert compact.endswith('."')


def test_normalization_preserves_spacing_around_quotes_and_hyphen():
    sample = "“Still,” said Château-Renaud, “Dr. d’Avrigny, who attends my mother, declares he is in despair about it."
    normalized = _normalize_text(sample)

    assert normalized.startswith(
        "“Still,” said Château-Renaud, “Doctor d'Avrigny, who attends my mother, declares he is in despair about it."
    )
    assert "  " not in normalized
    assert "Château-Renaud" in normalized
    assert "Doctor d'Avrigny" in normalized


def test_normalize_roman_titles_converts_when_majority() -> None:
    titles = ["I: Opening", "II: Rising Action", "III: Climax"]
    normalized = normalize_roman_numeral_titles(titles)

    assert normalized == ["1: Opening", "2: Rising Action", "3: Climax"]


def test_normalize_roman_titles_skips_when_not_majority() -> None:
    titles = ["Preface", "I: Opening", "Acknowledgements"]
    normalized = normalize_roman_numeral_titles(titles)

    assert normalized == titles


def test_normalize_roman_titles_preserves_separators() -> None:
    titles = ["  IV.  The Trial", "V - The Verdict", "VI\nAftermath"]
    normalized = normalize_roman_numeral_titles(titles)

    assert normalized[0] == "  4.  The Trial"
    assert normalized[1] == "5 - The Verdict"
    assert normalized[2].startswith("6\nAftermath")


def test_grouped_numbers_are_spelled_out() -> None:
    normalized = _normalize_text("The vault holds 35,000 credits")
    assert "thirty-five thousand" in normalized.lower()


def test_numeric_ranges_are_spoken_with_to() -> None:
    normalized = _normalize_text("Chapters 1-3")
    assert "one to three" in normalized.lower()


def test_simple_fractions_are_spoken() -> None:
    normalized = _normalize_text("Add 1/2 cup of sugar")
    assert "one half" in normalized.lower()


def test_plain_numbers_are_spelled_out() -> None:
    normalized = _normalize_text("He rolled a 42.")
    assert "forty-two" in normalized.lower()


def test_decimal_numbers_include_point() -> None:
    normalized = _normalize_text("Book 4.5 of the series.")
    assert "four point five" in normalized.lower()


def test_space_separated_numbers_become_ranges() -> None:
    normalized = _normalize_text("Read pages 12 14 tonight.")
    assert "pages twelve to fourteen" in normalized.lower()


def test_year_like_numbers_use_common_pronunciation() -> None:
    normalized = _normalize_text("In 1924 the journey began")
    folded = normalized.lower().replace("-", " ")
    assert "nineteen hundred" in folded
    assert "twenty four" in folded


def test_early_century_years_use_hundred_format() -> None:
    normalized = _normalize_text("In 1204 the city fell")
    assert "twelve hundred" in normalized.lower()
    assert "oh four" in normalized.lower()


def test_roman_numerals_in_titles_are_converted() -> None:
    normalized = _normalize_text("Chapter IV begins now")
    assert "chapter four" in normalized.lower()


def test_roman_numeral_suffixes_use_ordinals() -> None:
    normalized = _normalize_text("Bob Smith II arrived late")
    assert "bob smith the second" in normalized.lower()


def test_lowercase_roman_after_part_converts_to_cardinal() -> None:
    normalized = _normalize_text("We studied part iii of the manuscript.")
    assert "part three" in normalized.lower()


def test_hyphenated_phase_with_roman_is_converted() -> None:
    normalized = _normalize_text("They executed phase-IV without delay.")
    assert "phase four" in normalized.lower()


def test_all_caps_quotes_are_sentence_cased() -> None:
    normalized = _normalize_text('"THIS IS A TEST."')
    cleaned = normalized.replace('" ', '"')
    assert '"This is a test."' in cleaned


def test_caps_quote_preserves_acronyms() -> None:
    normalized = _normalize_text("“THE NASA TEAM ARRIVED.”")
    assert "“The NASA team arrived.”" in normalized


def test_caps_quote_normalization_respects_override() -> None:
    normalized = _normalize_text(
        '"KEEP SHOUTING."',
        normalization_overrides={"normalization_caps_quotes": False},
    )
    cleaned = normalized.replace('" ', '"')
    assert '"KEEP SHOUTING."' in cleaned


def test_recent_years_split_twenty_style() -> None:
    normalized = _normalize_text("In 2025 we planned ahead")
    folded = normalized.lower().replace("-", " ")
    assert "twenty twenty five" in folded


def test_two_thousands_use_two_thousand_prefix() -> None:
    normalized = _normalize_text("In 2005 we celebrated")
    assert "two thousand five" in normalized.lower()


def test_year_style_can_be_disabled() -> None:
    normalized = _normalize_text(
        "In 2025 we planned ahead",
        normalization_overrides={"normalization_numbers_year_style": "off"},
    )
    folded = normalized.lower().replace("-", " ")
    assert "twenty twenty five" not in folded


def test_contractions_can_be_kept_when_override_disabled() -> None:
    normalized = _normalize_text(
        "It's a good day.",
        normalization_overrides={"normalization_apostrophes_contractions": False},
    )
    assert "It's" in normalized


def test_sibilant_possessives_remain_when_marking_disabled() -> None:
    normalized = _normalize_text(
        "The boss's chair wobbled.",
        normalization_overrides={"normalization_apostrophes_sibilant_possessives": False},
    )
    assert "boss's" in normalized
    assert "boss iz" not in normalized.lower()


def test_decades_can_skip_expansion_when_disabled() -> None:
    normalized = _normalize_text(
        "Classic hits from the '90s filled the hall.",
        normalization_overrides={"normalization_apostrophes_decades": False},
    )
    assert "'90s" in normalized


def test_abbreviated_decades_expand_to_spoken_form() -> None:
    normalized = _normalize_text("She loved music from the '80s.")
    assert "eighties" in normalized.lower()


def test_currency_under_one_dollar_uses_cents() -> None:
    normalized = _normalize_text("It cost $0.99.")
    folded = normalized.lower().replace("-", " ")
    assert "zero dollars" not in folded
    assert "cents" in folded


def test_iso_dates_use_locale_order_and_ordinals(monkeypatch) -> None:
    monkeypatch.setenv("LC_TIME", "en_US.UTF-8")
    normalized = _normalize_text("The date is 2025/12/15.")
    folded = normalized.lower().replace("-", " ")
    assert "december" in folded
    assert "fifteenth" in folded


def test_times_and_acronyms_do_not_say_dot() -> None:
    normalized = _normalize_text("Meet at 5 p.m. near the U.S.A. border.")
    folded = normalized.lower()
    assert " dot " not in folded


def test_internet_slang_expansion_is_configurable() -> None:
    normalized = _normalize_text(
        "pls knock before entering.",
        normalization_overrides={"normalization_internet_slang": True},
    )
    assert "please" in normalized.lower()


@pytest.mark.skipif(not SPACY_RESOLVER_AVAILABLE, reason="spaCy model unavailable")
def test_spacy_disambiguates_it_has_from_context() -> None:
    normalized = _normalize_text("It's been a long time.")
    assert "It has been a long time." == normalized


@pytest.mark.skipif(not SPACY_RESOLVER_AVAILABLE, reason="spaCy model unavailable")
def test_spacy_disambiguates_it_is_from_context() -> None:
    normalized = _normalize_text("It's cold outside.")
    assert "It is cold outside." == normalized


@pytest.mark.skipif(not SPACY_RESOLVER_AVAILABLE, reason="spaCy model unavailable")
def test_spacy_disambiguates_she_had() -> None:
    normalized = _normalize_text("She'd left before dawn.")
    assert "She had left before dawn." == normalized


@pytest.mark.skipif(not SPACY_RESOLVER_AVAILABLE, reason="spaCy model unavailable")
def test_spacy_disambiguates_she_would() -> None:
    normalized = _normalize_text("She'd go if invited.")
    assert "She would go if invited." == normalized


@pytest.mark.skipif(not SPACY_RESOLVER_AVAILABLE, reason="spaCy model unavailable")
def test_sample_sentence_handles_complex_contractions() -> None:
    sample = "I've heard the captain'll arrive by dusk, but they'd said the same yesterday."
    normalized = _normalize_text(sample)
    assert (
        "I have heard the captain will arrive by dusk, but they had said the same yesterday." == normalized
    )


def test_modal_will_contractions_can_be_disabled() -> None:
    sample = "The captain'll arrive at dawn."
    normalized = _normalize_text(
        sample,
        normalization_overrides={"normalization_contraction_modal_will": False},
    )
    assert "captain'll" in normalized


@pytest.fixture(autouse=True)
def mock_settings():
    defaults = {
        "normalization_numbers": True,
        "normalization_titles": True,
        "normalization_terminal": True,
        "normalization_phoneme_hints": True,
        "normalization_caps_quotes": True,
        "normalization_apostrophes_contractions": True,
        "normalization_apostrophes_plural_possessives": True,
        "normalization_apostrophes_sibilant_possessives": True,
        "normalization_apostrophes_decades": True,
        "normalization_apostrophes_leading_elisions": True,
        "normalization_apostrophe_mode": "spacy",
        "normalization_contraction_aux_be": True,
        "normalization_contraction_aux_have": True,
        "normalization_contraction_modal_will": True,
        "normalization_contraction_modal_would": True,
        "normalization_contraction_negation_not": True,
        "normalization_contraction_let_us": True,
        "normalization_currency": True,
        "normalization_footnotes": True,
        "normalization_numbers_year_style": "american",
    }
    with patch("tests.test_text_normalization.get_runtime_settings", return_value=defaults):
        yield

def test_currency_magnitude():
    cases = [
        ("$2 million", "two million dollars"),
        ("$2.5 million", "two point five million dollars"),
        ("$100 billion", "one hundred billion dollars"),
        ("$1.2 trillion", "one point two trillion dollars"),
        ("$2.55 million", "two point five five million dollars"),
        ("$1 million", "one million dollars"),
        ("$0.5 million", "zero point five million dollars"),
        ("$2.50", "two dollars, fifty cents"),
        ("$100", "one hundred dollars"),
    ]
    
    settings = {
        "normalization_numbers": True,
        "normalization_currency": True,
        "normalization_apostrophe_mode": "spacy"
    }
    
    for input_text, expected in cases:
        normalized = _normalize_text(input_text, normalization_overrides=settings)
        assert expected.lower() in normalized.lower(), f"Failed for {input_text}: got '{normalized}'"
