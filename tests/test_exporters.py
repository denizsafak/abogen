"""Tests for ExportService FFmpeg metadata methods."""
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from pathlib import Path
from unittest.mock import patch

import pytest

from abogen.infrastructure.exporters import ExportService


class TestEscapeFfmetadataValue:
    def setup_method(self):
        self.svc = ExportService()

    def test_simple_string(self):
        assert self.svc._escape_ffmetadata_value("hello") == "hello"

    def test_escapes_backslash(self):
        assert self.svc._escape_ffmetadata_value("a\\b") == "a\\\\b"

    def test_escapes_newline(self):
        assert self.svc._escape_ffmetadata_value("line1\nline2") == "line1\\nline2"

    def test_escapes_equals(self):
        assert self.svc._escape_ffmetadata_value("key=value") == "key\\=value"

    def test_escapes_semicolon(self):
        assert self.svc._escape_ffmetadata_value("a;b") == "a\\;b"

    def test_escapes_hash(self):
        assert self.svc._escape_ffmetadata_value("#comment") == "\\#comment"

    def test_escapes_all_special(self):
        result = self.svc._escape_ffmetadata_value("a\\b\nc=d;e#f")
        assert "\\\\" in result
        assert "\\n" in result
        assert "\\=" in result
        assert "\\;" in result
        assert "\\#" in result

    def test_empty_string(self):
        assert self.svc._escape_ffmetadata_value("") == ""


class TestRenderFfmetadata:
    def setup_method(self):
        self.svc = ExportService()

    def test_renders_header(self):
        result = self.svc.render_ffmetadata({"title": "My Book"}, [])
        assert result.startswith(";FFMETADATA1\n")
        assert "title=My Book\n" in result

    def test_renders_multiple_keys(self):
        result = self.svc.render_ffmetadata({"title": "T", "artist": "A"}, [])
        assert "title=T\n" in result
        assert "artist=A\n" in result

    def test_skips_none_values(self):
        result = self.svc.render_ffmetadata({"title": None}, [])
        assert "title=" not in result

    def test_renders_chapters(self):
        chapters = [{"start": 0.0, "end": 10.0, "title": "Ch 1"}]
        result = self.svc.render_ffmetadata({}, chapters)
        assert "[CHAPTER]" in result
        assert "TIMEBASE=1/1000" in result
        assert "START=0" in result
        assert "END=10000" in result
        assert "title=Ch 1" in result

    def test_renders_voice_in_chapter(self):
        chapters = [{"start": 0.0, "end": 5.0, "voices": [{"provider": "kokoro", "voice": "af_heart"}]}]
        result = self.svc.render_ffmetadata({}, chapters)
        assert "voice=af_heart@kokoro" in result

    def test_skips_chapters_without_times(self):
        chapters = [{"title": "No times"}]
        result = self.svc.render_ffmetadata({}, chapters)
        assert "[CHAPTER]" not in result

    def test_end_equals_start_gets_minimum_duration(self):
        chapters = [{"start": 5.0, "end": 5.0, "title": "Zero"}]
        result = self.svc.render_ffmetadata({}, chapters)
        assert "START=5000" in result
        assert "END=5001" in result

    def test_empty_metadata_and_chapters(self):
        result = self.svc.render_ffmetadata({}, [])
        assert result.strip() == ";FFMETADATA1"

    def test_escapes_special_chars_in_title(self):
        chapters = [{"start": 0.0, "end": 1.0, "title": "A=B;C#D"}]
        result = self.svc.render_ffmetadata({}, chapters)
        assert "\\=" in result
        assert "\\;" in result
        assert "\\#" in result

    def test_negative_start_clamped_to_zero(self):
        chapters = [{"start": -1.0, "end": 5.0, "title": "Neg"}]
        result = self.svc.render_ffmetadata({}, chapters)
        assert "START=0" in result


class TestMetadataToFfmpegArgs:
    def setup_method(self):
        self.svc = ExportService()

    def test_simple_metadata(self):
        args = self.svc._metadata_to_ffmpeg_args({"title": "My Book"})
        assert args == ["-metadata", "title=My Book"]

    def test_year_becomes_date(self):
        args = self.svc._metadata_to_ffmpeg_args({"year": "2024"})
        assert args == ["-metadata", "date=2024"]

    def test_skips_none_and_empty(self):
        args = self.svc._metadata_to_ffmpeg_args({"title": None, "artist": ""})
        assert args == []

    def test_skips_empty_key(self):
        args = self.svc._metadata_to_ffmpeg_args({"": "value"})
        assert args == []

    def test_multiple_keys(self):
        args = self.svc._metadata_to_ffmpeg_args({"title": "T", "artist": "A"})
        assert "-metadata" in args
        assert "title=T" in args
        assert "artist=A" in args

    def test_empty_metadata(self):
        assert self.svc._metadata_to_ffmpeg_args({}) == []

    def test_none_metadata(self):
        assert self.svc._metadata_to_ffmpeg_args(None) == []


class TestWriteFfmetadataFile:
    def setup_method(self):
        self.svc = ExportService()

    def test_writes_file(self, tmp_path):
        audio = tmp_path / "test.mp3"
        audio.touch()
        meta = {"title": "My Book"}
        chapters = [{"start": 0.0, "end": 5.0, "title": "Ch 1"}]
        result = self.svc.write_ffmetadata_file(audio, meta, chapters)
        assert result is not None
        assert result.exists()
        content = result.read_text()
        assert ";FFMETADATA1" in content
        assert "title=My Book" in content

    def test_returns_none_for_empty(self, tmp_path):
        audio = tmp_path / "test.mp3"
        audio.touch()
        result = self.svc.write_ffmetadata_file(audio, {}, [])
        assert result is None

    def test_returns_none_for_only_header(self, tmp_path):
        audio = tmp_path / "test.mp3"
        audio.touch()
        result = self.svc.write_ffmetadata_file(audio, None, None)
        assert result is None


class TestApplyM4bChaptersMutagen:
    """_apply_m4b_chapters_mutagen log behavior (see denizsafak/abogen#195).

    Current mutagen releases expose no writable MP4 chapter API
    (mutagen.mp4.MP4Chapter does not exist), so the import inside this
    method can never succeed. The method must therefore return False and
    log an *accurate* message: a warning only when mutagen is genuinely
    missing, and a debug note (not a scary warning) when mutagen is
    installed but lacks the writable API.
    """

    def setup_method(self):
        self.svc = ExportService()

    def test_empty_chapters_returns_false_without_logging(self, tmp_path):
        logs = []
        result = self.svc._apply_m4b_chapters_mutagen(
            tmp_path / "out.m4b", [], lambda msg, lvl: logs.append((lvl, msg))
        )
        assert result is False
        assert logs == []

    def test_mutagen_installed_without_writable_api_logs_debug_not_warning(self, tmp_path):
        """mutagen IS installed (the normal case) -> accurate debug, no warning.

        This is the regression #195 reported: the old code always logged
        'mutagen is not installed' (a warning), which was misleading.
        """
        import mutagen  # noqa: F401  (present in the test env; CI installs it)

        logs = []
        chapters = [{"start": 0.0, "end": 1.0, "title": "Ch 1"}]
        result = self.svc._apply_m4b_chapters_mutagen(
            tmp_path / "out.m4b", chapters, lambda msg, lvl: logs.append((lvl, msg))
        )
        assert result is False
        # No misleading warning in the expected case.
        assert not any(lvl == "warning" for lvl, _ in logs), logs
        # An accurate, non-alarming note instead.
        assert any(
            lvl == "debug" and "writable MP4 chapter API" in msg for lvl, msg in logs
        ), logs

    def test_mutagen_genuinely_missing_still_warns(self, tmp_path):
        """mutagen truly absent -> keep the original warning (backward-compat)."""
        with patch.dict("sys.modules", {"mutagen": None, "mutagen.mp4": None}):
            logs = []
            chapters = [{"start": 0.0, "end": 1.0, "title": "Ch 1"}]
            result = self.svc._apply_m4b_chapters_mutagen(
                tmp_path / "out.m4b", chapters, lambda msg, lvl: logs.append((lvl, msg))
            )
        assert result is False
        assert any(
            lvl == "warning" and "mutagen is not installed" in msg for lvl, msg in logs
        ), logs
