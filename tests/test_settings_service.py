"""Tests for webui/services/settings_service.py — form→settings mapping."""

from collections import OrderedDict

from abogen.webui.services.settings_service import apply_form_to_settings


def _form(**kwargs: str | None) -> dict[str, str | None]:
    return OrderedDict(kwargs)


def _base() -> dict:
    return {
        "language": "en",
        "default_speaker": "",
        "default_voice": "",
        "supertonic_total_steps": 5,
        "supertonic_speed": 1.0,
        "output_format": "mp3",
        "subtitle_mode": "Disabled",
        "subtitle_format": "srt",
        "save_mode": "save_next_to_input",
        "replace_single_newlines": False,
        "use_gpu": False,
        "save_chapters_separately": False,
        "merge_chapters_at_end": True,
        "save_as_project": False,
        "separate_chapters_format": "wav",
        "silence_between_chapters": 2.0,
        "chapter_intro_delay": 0.5,
        "read_title_intro": False,
        "read_closing_outro": True,
        "normalize_chapter_opening_caps": True,
        "auto_prefix_chapter_titles": True,
        "max_subtitle_words": 50,
        "chunk_level": "paragraph",
        "generate_epub3": False,
        "speaker_analysis_threshold": 15,
        "integrations": {},
    }


class TestApplyFormToSettings:
    def test_general_fields(self):
        settings = _base()
        form = _form(language="fr", default_speaker="af_heart", output_format="wav")
        apply_form_to_settings(settings, form)
        assert settings["language"] == "fr"
        assert settings["default_speaker"] == "af_heart"
        assert settings["output_format"] == "wav"

    def test_numeric_fields(self):
        settings = _base()
        form = _form(supertonic_total_steps="10", supertonic_speed="1.5", max_subtitle_words="30")
        apply_form_to_settings(settings, form)
        assert settings["supertonic_total_steps"] == 10
        assert settings["supertonic_speed"] == 1.5
        assert settings["max_subtitle_words"] == 30

    def test_numeric_clamping(self):
        settings = _base()
        form = _form(supertonic_total_steps="100", supertonic_speed="5.0", max_subtitle_words="0")
        apply_form_to_settings(settings, form)
        assert settings["supertonic_total_steps"] == 15
        assert settings["supertonic_speed"] == 2.0
        assert settings["max_subtitle_words"] == 1

    def test_boolean_checkboxes(self):
        settings = _base()
        form = _form(use_gpu="on", save_chapters_separately="on")
        apply_form_to_settings(settings, form)
        assert settings["use_gpu"] is True
        assert settings["save_chapters_separately"] is True

    def test_default_values_preserved(self):
        settings = _base()
        form = _form()
        apply_form_to_settings(settings, form)
        assert settings["silence_between_chapters"] == 2.0
        assert settings["chunk_level"] == "paragraph"

    def test_empty_form_keeps_general_defaults(self):
        settings = _base()
        apply_form_to_settings(settings, _form())
        # General fields should stay at their base values
        assert settings["language"] == "en"
        assert settings["output_format"] == "mp3"
        assert settings["chunk_level"] == "paragraph"
        assert settings["silence_between_chapters"] == 2.0

    def test_language_whitespace_trimmed(self):
        settings = _base()
        apply_form_to_settings(settings, _form(language="  de  "))
        assert settings["language"] == "de"
