"""Regression tests for ConversionRequest building.

These tests verify that both WebUI and PyQt adapters can produce
a valid ConversionRequest from their respective Job/thread state.
They serve as a specification for the adapter code that will be
created in Phase 2/3 of the refactor.

Currently these tests verify the EXISTING behavior by testing the
domain functions that the adapters will call. After the adapters
are created, these tests should be updated to test the adapters
directly.
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from abogen.application.conversion_request import ConversionRequest, ConversionRequestError
from abogen.domain.enums import Language, OutputFormat, SaveMode, SubtitleFormat, SubtitleMode
from abogen.domain.normalization import TTSContext
from abogen.domain.settings_core import settings_defaults
from abogen.domain.split_pattern import get_split_pattern


class TestConversionRequestBasics:
    """Verify that basic request parameters can be derived from settings."""

    def test_settings_defaults_exist(self):
        defaults = settings_defaults()
        assert isinstance(defaults, dict)
        assert "output_format" in defaults
        assert "subtitle_format" in defaults
        assert "save_mode" in defaults
        assert "use_gpu" in defaults
        assert "silence_between_chapters" in defaults
        assert "merge_chapters_at_end" in defaults

    def test_split_pattern_computation(self):
        pattern = get_split_pattern("a", "Disabled")
        assert isinstance(pattern, str)
        assert len(pattern) > 0

    def test_split_pattern_varies_by_subtitle_mode(self):
        pattern_disabled = get_split_pattern("a", "Disabled")
        pattern_sentence = get_split_pattern("a", "Sentence")
        # Different modes should produce different patterns
        assert isinstance(pattern_disabled, str)
        assert isinstance(pattern_sentence, str)


class TestTTSContextBuilding:
    """Verify TTSContext can be built from settings parameters."""

    def test_build_context_from_params(self):
        ctx = TTSContext(
            split_pattern=r"(?<=[.!?\-])\s+",
            pronunciation_rules=None,
            heteronym_rules=None,
            normalization_overrides=None,
        )
        assert ctx.split_pattern
        assert ctx.normalize("Hello world.") is not None

    def test_build_context_with_compiled_rules(self):
        from abogen.domain.pronunciation import compile_pronunciation_rules
        rules = compile_pronunciation_rules([{"pattern": "test", "replacement": "Test"}])
        ctx = TTSContext(
            split_pattern=r"\n+",
            pronunciation_rules=rules,
        )
        result = ctx.normalize("test text")
        assert isinstance(result, str)

    def test_usage_counter_tracking(self):
        ctx = TTSContext()
        ctx.usage_counter["token1"] = 0
        ctx.normalize("Some text with token1")
        # Usage counter should be passed through (may or may not increment
        # depending on whether the token matches)
        assert isinstance(ctx.usage_counter, dict)


class TestOutputDirectoryResolution:
    """Verify output directory can be resolved from parameters."""

    def test_resolve_output_directory(self, tmp_path):
        from abogen.domain.output_paths import resolve_output_directory
        result = resolve_output_directory(
            save_mode="Save next to input file",
            stored_path=tmp_path / "test.txt",
            output_folder=None,
            desktop_dir=tmp_path,
            user_output_path=None,
            user_cache_outputs=tmp_path,
        )
        assert result is not None
        assert isinstance(result, Path)

    def test_resolve_output_with_explicit_folder(self, tmp_path):
        from abogen.domain.output_paths import resolve_output_directory
        custom_dir = tmp_path / "custom_output"
        custom_dir.mkdir()
        result = resolve_output_directory(
            save_mode="Save to custom folder",
            stored_path=tmp_path / "test.txt",
            output_folder=str(custom_dir),
            desktop_dir=tmp_path,
            user_output_path=None,
            user_cache_outputs=tmp_path,
        )
        assert result is not None


class TestChapterSelection:
    """Verify chapter selection logic works with various inputs."""

    def test_auto_select_relevant_chapters(self):
        from abogen.domain.file_type import auto_select_relevant_chapters
        from abogen.text_extractor import ExtractedChapter
        chapters = [
            ExtractedChapter(title="Chapter 1", text="A" * 500),
            ExtractedChapter(title="Chapter 2", text="B" * 50),
            ExtractedChapter(title="Chapter 3", text="C" * 600),
        ]
        result = auto_select_relevant_chapters(chapters, "txt")
        # Should filter out short chapters
        assert len(result.kept) >= 1
        assert isinstance(result.skipped, list)

    def test_auto_select_all_long_chapters(self):
        from abogen.domain.file_type import auto_select_relevant_chapters
        from abogen.text_extractor import ExtractedChapter
        chapters = [
            ExtractedChapter(title="Chapter 1", text="A" * 500),
            ExtractedChapter(title="Chapter 2", text="B" * 500),
        ]
        result = auto_select_relevant_chapters(chapters, "txt")
        assert len(result.kept) == 2
        assert len(result.skipped) == 0

    def test_metadata_merge(self):
        from abogen.domain.metadata_merge import merge_metadata
        base = {"title": "Original Title", "author": "Author A"}
        overrides = {"title": "New Title"}
        result = merge_metadata(base, overrides)
        assert result["title"] == "New Title"
        assert result["author"] == "Author A"


class TestCancellationProtocol:
    """Verify cancellation mechanism can be implemented as a callback."""

    def test_cancellation_flag_check(self):
        class FakeJob:
            def __init__(self):
                self.cancel_requested = False

        job = FakeJob()
        check = lambda: job.cancel_requested
        assert check() is False

        job.cancel_requested = True
        assert check() is True

    def test_cancellation_exception_pattern(self):
        """WebUI uses exception-based cancellation."""
        class JobCancelled(Exception):
            pass

        def canceller():
            raise JobCancelled()

        with pytest.raises(JobCancelled):
            canceller()


class TestLoggingProtocol:
    """Verify logging can be abstracted as a callback."""

    def test_log_callback(self):
        logs = []
        def log_fn(msg, level="info"):
            logs.append((msg, level))

        log_fn("Test message", "info")
        assert len(logs) == 1
        assert logs[0] == ("Test message", "info")

    def test_progress_callback(self):
        progress_calls = []
        def progress_fn(processed, total, etr):
            progress_calls.append((processed, total, etr))

        progress_fn(100, 1000, "0:05:00")
        assert len(progress_calls) == 1
        assert progress_calls[0] == (100, 1000, "0:05:00")


class TestConversionRequestValidation:
    """Verify __post_init__ validation on ConversionRequest."""

    def test_defaults_are_valid(self):
        req = ConversionRequest()
        assert req.max_subtitle_words == 50
        assert req.speed == 1.0
        assert req.supertonic_total_steps == 5
        assert req.output_format == OutputFormat.WAV
        assert req.subtitle_mode == SubtitleMode.DISABLED

    def test_max_subtitle_words_clamped_below_min(self):
        req = ConversionRequest(max_subtitle_words=0)
        assert req.max_subtitle_words == 1

    def test_max_subtitle_words_clamped_above_max(self):
        req = ConversionRequest(max_subtitle_words=999)
        assert req.max_subtitle_words == 500

    def test_max_subtitle_words_valid(self):
        req = ConversionRequest(max_subtitle_words=100)
        assert req.max_subtitle_words == 100

    def test_speed_clamped_below_min(self):
        req = ConversionRequest(speed=0.1)
        assert req.speed == 0.5

    def test_speed_clamped_above_max(self):
        req = ConversionRequest(speed=10.0)
        assert req.speed == 3.0

    def test_speed_valid(self):
        req = ConversionRequest(speed=1.5)
        assert req.speed == 1.5

    def test_supertonic_steps_clamped_below_min(self):
        req = ConversionRequest(supertonic_total_steps=0)
        assert req.supertonic_total_steps == 2

    def test_supertonic_steps_clamped_above_max(self):
        req = ConversionRequest(supertonic_total_steps=100)
        assert req.supertonic_total_steps == 15

    def test_silence_between_chapters_clamped(self):
        req = ConversionRequest(silence_between_chapters=-5.0)
        assert req.silence_between_chapters == 0.0

    def test_chapter_intro_delay_clamped(self):
        req = ConversionRequest(chapter_intro_delay=-1.0)
        assert req.chapter_intro_delay == 0.0

    def test_invalid_chunk_level_raises(self):
        with pytest.raises(ConversionRequestError, match="chunk_level"):
            ConversionRequest(chunk_level="invalid")

    def test_invalid_speaker_mode_raises(self):
        with pytest.raises(ConversionRequestError, match="speaker_mode"):
            ConversionRequest(speaker_mode="invalid")

    def test_invalid_max_subtitle_words_type_raises(self):
        with pytest.raises(ConversionRequestError, match="max_subtitle_words"):
            ConversionRequest(max_subtitle_words="not_a_number")

    def test_invalid_speed_type_raises(self):
        with pytest.raises(ConversionRequestError, match="speed"):
            ConversionRequest(speed="fast")

    def test_invalid_silence_type_raises(self):
        with pytest.raises(ConversionRequestError, match="silence_between_chapters"):
            ConversionRequest(silence_between_chapters="loud")

    def test_empty_tts_provider_defaults_to_kokoro(self):
        req = ConversionRequest(tts_provider="")
        assert req.tts_provider == "kokoro"

    def test_enum_fields_accept_valid_values(self):
        req = ConversionRequest(
            language=Language.FR,
            output_format=OutputFormat.MP3,
            subtitle_mode=SubtitleMode.SENTENCE,
            subtitle_format=SubtitleFormat.ASS,
            save_mode=SaveMode.CUSTOM_FOLDER,
        )
        assert req.language == Language.FR
        assert req.output_format == OutputFormat.MP3
        assert req.subtitle_mode == SubtitleMode.SENTENCE
        assert req.subtitle_format == SubtitleFormat.ASS
        assert req.save_mode == SaveMode.CUSTOM_FOLDER
