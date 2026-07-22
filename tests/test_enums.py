"""Tests for domain enums — validation, properties, from_str methods."""

import pytest
from pathlib import Path

from abogen.domain.enums import (
    InputFormat,
    Language,
    OutputFormat,
    SaveMode,
    SubtitleFormat,
    SubtitleMode,
)


class TestSubtitleMode:
    def test_from_str_case_insensitive(self):
        assert SubtitleMode.from_str("disabled") == SubtitleMode.DISABLED
        assert SubtitleMode.from_str("SENTENCE") == SubtitleMode.SENTENCE
        assert SubtitleMode.from_str("line") == SubtitleMode.LINE

    def test_from_str_strips_whitespace(self):
        assert SubtitleMode.from_str("  Disabled  ") == SubtitleMode.DISABLED

    def test_from_str_invalid(self):
        with pytest.raises(ValueError, match="Invalid SubtitleMode"):
            SubtitleMode.from_str("invalid")

    def test_comparison_with_str(self):
        assert SubtitleMode.DISABLED == "Disabled"
        assert SubtitleMode.SENTENCE != "Disabled"


class TestOutputFormat:
    def test_dot_ext(self):
        assert OutputFormat.WAV.dot_ext == ".wav"
        assert OutputFormat.M4B.dot_ext == ".m4b"

    def test_is_lossless(self):
        assert OutputFormat.WAV.is_lossless is True
        assert OutputFormat.FLAC.is_lossless is True
        assert OutputFormat.MP3.is_lossless is False
        assert OutputFormat.M4B.is_lossless is False

    def test_from_str_strips_dot(self):
        assert OutputFormat.from_str(".wav") == OutputFormat.WAV
        assert OutputFormat.from_str(".MP3") == OutputFormat.MP3

    def test_from_str_case_insensitive(self):
        assert OutputFormat.from_str("WAV") == OutputFormat.WAV
        assert OutputFormat.from_str("opus") == OutputFormat.OPUS

    def test_from_str_invalid(self):
        with pytest.raises(ValueError, match="Invalid OutputFormat"):
            OutputFormat.from_str("avi")


class TestSaveMode:
    def test_values(self):
        assert SaveMode.SAVE_NEXT_TO_INPUT == "save_next_to_input"
        assert SaveMode.CUSTOM_FOLDER == "custom_folder"


class TestSubtitleFormat:
    def test_dot_ext(self):
        assert SubtitleFormat.SRT.dot_ext == ".srt"
        assert SubtitleFormat.ASS.dot_ext == ".ass"

    def test_from_str_strips_dot(self):
        assert SubtitleFormat.from_str(".srt") == SubtitleFormat.SRT
        assert SubtitleFormat.from_str(".ASS") == SubtitleFormat.ASS


class TestInputFormat:
    def test_is_book(self):
        assert InputFormat.EPUB.is_book is True
        assert InputFormat.PDF.is_book is True
        assert InputFormat.TXT.is_book is True
        assert InputFormat.MD.is_book is True
        assert InputFormat.SRT.is_book is False

    def test_is_subtitle(self):
        assert InputFormat.SRT.is_subtitle is True
        assert InputFormat.ASS.is_subtitle is True
        assert InputFormat.VTT.is_subtitle is True
        assert InputFormat.EPUB.is_subtitle is False

    def test_from_path(self):
        assert InputFormat.from_path(Path("book.epub")) == InputFormat.EPUB
        assert InputFormat.from_path(Path("sub.srt")) == InputFormat.SRT
        assert InputFormat.from_path(Path("notes.MD")) == InputFormat.MD
        assert InputFormat.from_path(Path("doc.markdown")) == InputFormat.MD

    def test_from_path_invalid(self):
        with pytest.raises(ValueError, match="Unsupported input format"):
            InputFormat.from_path(Path("video.mp4"))

    def test_dot_ext(self):
        assert InputFormat.EPUB.dot_ext == ".epub"
        assert InputFormat.SRT.dot_ext == ".srt"


class TestLanguage:
    def test_iso_codes(self):
        assert Language.EN_US == "en-US"
        assert Language.EN_GB == "en-GB"
        assert Language.ZH == "zh"
        assert Language.JA == "ja"

    def test_display_name(self):
        assert Language.EN_US.display_name == "American English"
        assert Language.JA.display_name == "Japanese"

    def test_is_cjk(self):
        assert Language.ZH.is_cjk is True
        assert Language.JA.is_cjk is True
        assert Language.EN_US.is_cjk is False

    def test_supports_subtitle_tokens(self):
        assert Language.EN_US.supports_subtitle_tokens is True
        assert Language.EN_GB.supports_subtitle_tokens is True
        assert Language.ZH.supports_subtitle_tokens is False

    def test_from_str_case_insensitive(self):
        assert Language.from_str("EN-US") == Language.EN_US
        assert Language.from_str("en-gb") == Language.EN_GB
        assert Language.from_str("ZH") == Language.ZH

    def test_from_str_invalid(self):
        with pytest.raises(ValueError, match="Invalid Language"):
            Language.from_str("en")
