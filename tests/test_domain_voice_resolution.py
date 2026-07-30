"""Tests for domain voice resolution functions.

Tests for formula_from_profile, resolve_profile_voice, resolve_voice_setting,
resolve_voice_choice, build_voice_catalog, and filter_voice_catalog.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# formula_from_profile
# ---------------------------------------------------------------------------


class TestFormulaFromProfile:
    """Tests for formula_from_profile()."""

    def test_kokoro_profile_with_voices(self):
        from abogen.domain.voice_resolution import formula_from_profile

        entry = {"voices": [("af_heart", 0.6), ("am_echo", 0.4)]}
        result = formula_from_profile(entry)
        assert result is not None
        assert "af_heart" in result
        assert "am_echo" in result

    def test_empty_voices_returns_none(self):
        from abogen.domain.voice_resolution import formula_from_profile

        entry = {"voices": []}
        assert formula_from_profile(entry) is None

    def test_no_voices_key_returns_none(self):
        from abogen.domain.voice_resolution import formula_from_profile

        entry = {"language": "a"}
        assert formula_from_profile(entry) is None

    def test_none_entry_returns_none(self):
        from abogen.domain.voice_resolution import formula_from_profile

        assert formula_from_profile(None) is None  # type: ignore

    def test_non_dict_entry_returns_none(self):
        from abogen.domain.voice_resolution import formula_from_profile

        assert formula_from_profile("invalid") is None  # type: ignore

    def test_supertonic_profile_no_voices(self):
        from abogen.domain.voice_resolution import formula_from_profile

        entry = {"provider": "supertonic", "voice": "M1"}
        assert formula_from_profile(entry) is None


# ---------------------------------------------------------------------------
# resolve_profile_voice
# ---------------------------------------------------------------------------


class TestResolveProfileVoice:
    """Tests for resolve_profile_voice()."""

    def test_resolves_kokoro_profile(self):
        from abogen.domain.voice_resolution import resolve_profile_voice

        profiles = {
            "MyMix": {
                "provider": "kokoro",
                "language": "a",
                "voices": [("af_heart", 0.5), ("am_echo", 0.5)],
            }
        }
        formula, language = resolve_profile_voice("MyMix", profiles=profiles)
        assert "af_heart" in formula
        assert "am_echo" in formula
        assert language == "a"

    def test_empty_profile_name(self):
        from abogen.domain.voice_resolution import resolve_profile_voice

        formula, language = resolve_profile_voice("", profiles={})
        assert formula == ""
        assert language is None

    def test_none_profile_name(self):
        from abogen.domain.voice_resolution import resolve_profile_voice

        formula, language = resolve_profile_voice(None, profiles={})
        assert formula == ""
        assert language is None

    def test_nonexistent_profile(self):
        from abogen.domain.voice_resolution import resolve_profile_voice

        formula, language = resolve_profile_voice("Nonexistent", profiles={})
        assert formula == ""
        assert language is None

    def test_profile_without_language(self):
        from abogen.domain.voice_resolution import resolve_profile_voice

        profiles = {
            "NoLang": {
                "provider": "kokoro",
                "voices": [("af_heart", 1.0)],
            }
        }
        formula, language = resolve_profile_voice("NoLang", profiles=profiles)
        assert "af_heart" in formula
        assert language is None


# ---------------------------------------------------------------------------
# resolve_voice_setting
# ---------------------------------------------------------------------------


class TestResolveVoiceSetting:
    """Tests for resolve_voice_setting()."""

    def test_plain_voice_spec(self):
        from abogen.domain.voice_resolution import resolve_voice_setting

        spec, profile, language = resolve_voice_setting("af_heart")
        assert spec == "af_heart"
        assert profile is None
        assert language is None

    def test_profile_prefix(self):
        from abogen.domain.voice_resolution import resolve_voice_setting

        profiles = {
            "MyMix": {
                "provider": "kokoro",
                "language": "a",
                "voices": [("af_heart", 0.5), ("am_echo", 0.5)],
            }
        }
        spec, profile, language = resolve_voice_setting("profile:MyMix", profiles=profiles)
        assert "af_heart" in spec
        assert profile == "MyMix"
        assert language == "a"

    def test_speaker_prefix(self):
        from abogen.domain.voice_resolution import resolve_voice_setting

        profiles = {
            "MyMix": {
                "provider": "kokoro",
                "language": "e",
                "voices": [("bf_sage", 1.0)],
            }
        }
        spec, profile, language = resolve_voice_setting("speaker:MyMix", profiles=profiles)
        assert "bf_sage" in spec
        assert profile == "MyMix"
        assert language == "e"

    def test_empty_value(self):
        from abogen.domain.voice_resolution import resolve_voice_setting

        spec, profile, language = resolve_voice_setting("")
        assert spec == ""
        assert profile is None
        assert language is None


# ---------------------------------------------------------------------------
# resolve_voice_choice
# ---------------------------------------------------------------------------


class TestResolveVoiceChoice:
    """Tests for resolve_voice_choice()."""

    def test_plain_voice(self):
        from abogen.domain.voice_resolution import resolve_voice_choice

        voice, lang, profile = resolve_voice_choice(
            language="a",
            base_voice="af_heart",
            profile_name="",
            custom_formula="",
            profiles={},
        )
        assert voice == "af_heart"
        assert lang == "a"
        assert profile is None

    def test_kokoro_profile(self):
        from abogen.domain.voice_resolution import resolve_voice_choice

        profiles = {
            "MyMix": {
                "provider": "kokoro",
                "language": "a",
                "voices": [("af_heart", 0.5), ("am_echo", 0.5)],
            }
        }
        voice, lang, profile = resolve_voice_choice(
            language="a",
            base_voice="af_heart",
            profile_name="MyMix",
            custom_formula="",
            profiles=profiles,
        )
        assert "af_heart" in voice
        assert "am_echo" in voice
        assert lang == "a"
        assert profile == "MyMix"

    def test_supertonic_profile(self):
        from abogen.domain.voice_resolution import resolve_voice_choice

        profiles = {
            "MyST": {
                "provider": "supertonic",
                "language": "a",
                "voice": "M1",
            }
        }
        voice, lang, profile = resolve_voice_choice(
            language="a",
            base_voice="M1",
            profile_name="MyST",
            custom_formula="",
            profiles=profiles,
        )
        assert voice == "speaker:MyST"
        assert lang == "a"
        assert profile == "MyST"

    def test_custom_formula_overrides_profile(self):
        from abogen.domain.voice_resolution import resolve_voice_choice

        profiles = {
            "MyMix": {
                "provider": "kokoro",
                "language": "a",
                "voices": [("af_heart", 1.0)],
            }
        }
        voice, lang, profile = resolve_voice_choice(
            language="a",
            base_voice="af_heart",
            profile_name="MyMix",
            custom_formula="af_heart*0.3+am_echo*0.7",
            profiles=profiles,
        )
        assert voice == "af_heart*0.3+am_echo*0.7"
        assert profile is None

    def test_profile_language_override(self):
        from abogen.domain.voice_resolution import resolve_voice_choice

        profiles = {
            "GermanMix": {
                "provider": "kokoro",
                "language": "g",
                "voices": [("af_heart", 1.0)],
            }
        }
        voice, lang, profile = resolve_voice_choice(
            language="a",
            base_voice="af_heart",
            profile_name="GermanMix",
            custom_formula="",
            profiles=profiles,
        )
        assert lang == "g"
        assert profile == "GermanMix"


# ---------------------------------------------------------------------------
# build_voice_catalog
# ---------------------------------------------------------------------------


class TestBuildVoiceCatalog:
    """Tests for build_voice_catalog()."""

    @patch("plugins.kokoro.engine.language_for_voice_id")
    @patch("abogen.domain.voice_catalog.get_voices")
    def test_builds_catalog_with_metadata(self, mock_voices, mock_lang):
        from abogen.domain.voice_catalog import build_voice_catalog

        mock_voices.return_value = ("af_heart", "am_echo")
        mock_lang.side_effect = lambda vid: MagicMock(value="a")

        catalog = build_voice_catalog()

        assert len(catalog) == 2
        assert catalog[0]["id"] == "af_heart"
        assert catalog[0]["gender"] == "Female"
        assert catalog[0]["gender_code"] == "f"
        assert catalog[0]["language"] == "a"
        assert "Heart" in catalog[0]["display_name"]

        assert catalog[1]["id"] == "am_echo"
        assert catalog[1]["gender"] == "Male"
        assert catalog[1]["gender_code"] == "m"

    @patch("plugins.kokoro.engine.language_for_voice_id")
    @patch("abogen.domain.voice_catalog.get_voices")
    def test_empty_voices(self, mock_voices, mock_lang):
        from abogen.domain.voice_catalog import build_voice_catalog

        mock_voices.return_value = ()

        catalog = build_voice_catalog()
        assert catalog == []

    @patch("plugins.kokoro.engine.language_for_voice_id")
    @patch("abogen.domain.voice_catalog.get_voices")
    def test_display_name_formatting(self, mock_voices, mock_lang):
        from abogen.domain.voice_catalog import build_voice_catalog

        mock_voices.return_value = ("bf_sage",)
        mock_lang.side_effect = lambda vid: MagicMock(value="a")

        catalog = build_voice_catalog()
        assert catalog[0]["display_name"] == "Sage"


# ---------------------------------------------------------------------------
# filter_voice_catalog
# ---------------------------------------------------------------------------


class TestFilterVoiceCatalog:
    """Tests for filter_voice_catalog()."""

    def _catalog(self):
        return [
            {"id": "af_heart", "language": "a", "gender_code": "f"},
            {"id": "am_echo", "language": "a", "gender_code": "m"},
            {"id": "bf_sage", "language": "b", "gender_code": "f"},
        ]

    def test_filter_by_female(self):
        from abogen.domain.voice_catalog import filter_voice_catalog

        result = filter_voice_catalog(self._catalog(), gender="female")
        assert "af_heart" in result
        assert "bf_sage" in result
        assert "am_echo" not in result

    def test_filter_by_male(self):
        from abogen.domain.voice_catalog import filter_voice_catalog

        result = filter_voice_catalog(self._catalog(), gender="male")
        assert "am_echo" in result
        assert "af_heart" not in result

    def test_filter_by_language(self):
        from abogen.domain.voice_catalog import filter_voice_catalog

        result = filter_voice_catalog(
            self._catalog(), gender="female", allowed_languages=["a"]
        )
        assert "af_heart" in result
        assert "bf_sage" not in result

    def test_fallback_to_any_gender(self):
        from abogen.domain.voice_catalog import filter_voice_catalog

        catalog = [
            {"id": "af_heart", "language": "a", "gender_code": "f"},
        ]
        result = filter_voice_catalog(catalog, gender="male")
        assert "af_heart" in result

    def test_fallback_to_any_language(self):
        from abogen.domain.voice_catalog import filter_voice_catalog

        catalog = [
            {"id": "af_heart", "language": "a", "gender_code": "f"},
        ]
        result = filter_voice_catalog(
            catalog, gender="female", allowed_languages=["b"]
        )
        assert "af_heart" in result

    def test_empty_catalog(self):
        from abogen.domain.voice_catalog import filter_voice_catalog

        result = filter_voice_catalog([], gender="female")
        assert result == []
