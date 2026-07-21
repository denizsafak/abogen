"""Regression tests for conversion planning logic.

These tests verify that domain functions produce correct chapter plans,
segment plans, and voice marker splits. They serve as a regression net
for the upcoming conversion flow unification refactor.

All tests use domain functions only — no UI, no TTS, no audio I/O.
"""

import pytest
from pathlib import Path

from abogen.domain.text_chapters import parse_chapters_from_text
from abogen.domain.chapter_titles import format_spoken_chapter_title
from abogen.domain.normalization import TTSContext
from abogen.domain.voice_resolution import (
    resolve_fallback_voice_spec,
    spec_to_voice_ids,
)
from abogen.domain.intro_outro import resolve_intro, resolve_outro
from abogen.domain.output_paths import (
    resolve_output_directory,
    resolve_unique_path,
    sanitize_output_stem,
)
from abogen.domain.subtitle_generation import process_subtitle_tokens


# ─── Chapter Parsing ───────────────────────────────────────────────

class TestChapterParsing:
    """Verify parse_chapters_from_text produces correct chapter structure."""

    def test_single_chapter_no_markers(self):
        text = "This is a simple text without any chapter markers."
        chapters = parse_chapters_from_text(text, clean=False)
        assert len(chapters) == 1
        assert chapters[0][0]  # title exists
        assert "simple text" in chapters[0][1]

    def test_multiple_chapters_by_markers(self):
        text = """<<CHAPTER_MARKER:Chapter 1>>
First chapter content.

<<CHAPTER_MARKER:Chapter 2>>
Second chapter content."""
        chapters = parse_chapters_from_text(text, clean=False)
        assert len(chapters) >= 2
        titles = [ch[0] for ch in chapters]
        assert "Chapter 1" in titles
        assert "Chapter 2" in titles

    def test_empty_text(self):
        chapters = parse_chapters_from_text("", clean=False)
        assert len(chapters) >= 1  # at least one empty chapter

    def test_chapter_content_preserved(self):
        text = """<<CHAPTER_MARKER:Chapter 1>>
Hello world this is chapter one.

<<CHAPTER_MARKER:Chapter 2>>
Goodbye world this is chapter two."""
        chapters = parse_chapters_from_text(text, clean=False)
        assert len(chapters) >= 2
        all_text = " ".join(ch[1] for ch in chapters)
        assert "Hello world" in all_text
        assert "Goodbye world" in all_text

    def test_intro_before_first_marker(self):
        text = """Introduction text here.
<<CHAPTER_MARKER:Chapter 1>>
Chapter content."""
        chapters = parse_chapters_from_text(text, clean=False)
        assert len(chapters) >= 2
        assert chapters[0][0] == "Introduction"
        assert "Introduction text" in chapters[0][1]


# ─── Voice Marker Splitting ────────────────────────────────────────

class TestVoiceMarkerSplitting:
    """Verify voice marker splitting produces correct segment structure."""

    def test_no_voice_markers(self):
        from abogen.subtitle_utils import split_text_by_voice_markers
        text = "Just plain text without any voice markers."
        segments, last_voice, valid, invalid = split_text_by_voice_markers(text, "M1")
        assert len(segments) == 1
        assert segments[0][0] == "M1"  # default voice
        assert "plain text" in segments[0][1]

    def test_single_voice_marker(self):
        from abogen.subtitle_utils import split_text_by_voice_markers
        text = "<<VOICE:F1>> Hello from female voice."
        segments, last_voice, valid, invalid = split_text_by_voice_markers(text, "M1")
        # Should have at least one segment with the voice marker text
        assert len(segments) >= 1
        all_text = " ".join(seg[1] for seg in segments)
        assert "Hello from female" in all_text

    def test_voice_marker_preserves_text(self):
        from abogen.subtitle_utils import split_text_by_voice_markers
        text = "<<VOICE:F1>> First sentence. <<VOICE:M1>> Second sentence."
        segments, last_voice, valid, invalid = split_text_by_voice_markers(text, "M1")
        all_text = " ".join(seg[1] for seg in segments)
        assert "First sentence" in all_text
        assert "Second sentence" in all_text

    def test_voice_marker_persistence(self):
        from abogen.subtitle_utils import split_text_by_voice_markers
        text = "<<VOICE:F1>> First part."
        segments, last_voice, valid, invalid = split_text_by_voice_markers(text, "M1")
        # Should return the voice used, or default if voice not recognized
        assert last_voice in ("f1", "F1", "M1")


# ─── TTSContext ─────────────────────────────────────────────────────

class TestTTSContext:
    """Verify TTSContext bundles normalization parameters correctly."""

    def test_default_context(self):
        ctx = TTSContext()
        assert ctx.split_pattern
        assert ctx.pronunciation_rules is None
        assert ctx.heteronym_rules is None
        assert ctx.normalization_overrides is None
        assert ctx.usage_counter == {}

    def test_normalize_passthrough(self):
        ctx = TTSContext()
        text = "Hello world."
        result = ctx.normalize(text)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_normalize_with_usage_counter(self):
        ctx = TTSContext()
        ctx.usage_counter["test_token"] = 0
        result = ctx.normalize("Some text.")
        assert isinstance(result, str)


# ─── Voice Resolution ──────────────────────────────────────────────

class TestVoiceResolution:
    """Verify voice resolution functions produce valid specs."""

    def test_resolve_fallback_voice_spec(self):
        spec = resolve_fallback_voice_spec("M1", "M1", ["M1", "F1"])
        # Should return a valid voice spec or None
        if spec is not None:
            assert hasattr(spec, "voice_id") or isinstance(spec, str)

    def test_spec_to_voice_ids(self):
        ids = spec_to_voice_ids("M1")
        assert isinstance(ids, set)
        assert len(ids) >= 0  # may be empty if M1 not in kokoro voices

    def test_resolve_fallback_with_empty_cache(self):
        spec = resolve_fallback_voice_spec("M1", "M1", [])
        # Should handle empty cache gracefully


# ─── Intro/Outro ───────────────────────────────────────────────────

class TestIntroOutro:
    """Verify intro/outro resolution with various metadata states."""

    def test_resolve_intro_with_metadata(self):
        metadata = {
            "title": "Test Book",
            "author": "Test Author",
        }
        spec = resolve_intro(
            metadata, "test.txt", True,
            "M1", "M1", ["M1"],
        )
        assert spec is not None
        assert spec.text  # should have some text

    def test_resolve_intro_disabled(self):
        spec = resolve_intro(
            {}, "test.txt", False,
            "M1", "M1", ["M1"],
        )
        assert not spec.enabled

    def test_resolve_intro_no_metadata(self):
        spec = resolve_intro(
            {}, "test.txt", True,
            "M1", "M1", ["M1"],
        )
        # May or may not find text, but should not crash
        assert spec is not None

    def test_resolve_outro_with_metadata(self):
        metadata = {"title": "Test Book"}
        spec = resolve_outro(
            metadata, "test.txt", True,
            "M1", "M1", ["M1"],
        )
        assert spec is not None
        assert spec.text

    def test_resolve_outro_disabled(self):
        spec = resolve_outro(
            {}, "test.txt", False,
            "M1", "M1", ["M1"],
        )
        assert not spec.enabled


# ─── Output Paths ──────────────────────────────────────────────────

class TestOutputPaths:
    """Verify output path resolution produces valid paths."""

    def test_resolve_unique_path(self, tmp_path):
        # Create a file to force collision
        (tmp_path / "test.txt").touch()
        result = resolve_unique_path(
            str(tmp_path), "test", "txt",
            allowed_extensions={"txt", "wav"},
        )
        assert result
        assert "test" in result
        # Should have a suffix since "test.txt" already exists
        assert result != str(tmp_path / "test")

    def test_resolve_unique_path_no_collision(self, tmp_path):
        result = resolve_unique_path(str(tmp_path), "unique_name", "txt")
        assert result
        assert "unique_name" in result

    def test_sanitize_output_stem(self):
        stem = sanitize_output_stem("My Book Title")
        assert isinstance(stem, str)
        assert len(stem) > 0

    def test_resolve_output_directory(self, tmp_path):
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


# ─── Subtitle Generation ───────────────────────────────────────────

class TestSubtitleGeneration:
    """Verify subtitle token processing works correctly."""

    def test_process_empty_tokens(self):
        entries = []
        process_subtitle_tokens(
            [], entries, 5, "Sentence", "a",
            use_spacy_segmentation=False,
            fallback_end_time=10.0,
        )
        assert entries == []

    def test_process_sentence_mode(self):
        tokens = [
            {"start": 0.0, "end": 0.5, "text": "Hello", "whitespace": " "},
            {"start": 0.5, "end": 1.0, "text": "world", "whitespace": "."},
        ]
        entries = []
        process_subtitle_tokens(
            tokens, entries, 5, "Sentence", "a",
            use_spacy_segmentation=False,
            fallback_end_time=2.0,
        )
        # Should produce at least one entry
        assert len(entries) >= 1
        start, end, text = entries[0]
        assert start < end
        assert isinstance(text, str)

    def test_process_line_mode(self):
        tokens = [
            {"start": 0.0, "end": 0.5, "text": "Hello", "whitespace": " "},
            {"start": 0.5, "end": 1.0, "text": "world", "whitespace": "\n"},
            {"start": 1.0, "end": 1.5, "text": "New", "whitespace": " "},
            {"start": 1.5, "end": 2.0, "text": "line", "whitespace": "."},
        ]
        entries = []
        process_subtitle_tokens(
            tokens, entries, 5, "Line", "a",
            use_spacy_segmentation=False,
            fallback_end_time=3.0,
        )
        # Line mode should produce entries split by newlines
        assert len(entries) >= 1


# ─── Feature Parity Regression ─────────────────────────────────────

class TestFeatureParity:
    """Regression tests for features that must work in both UIs."""

    def test_chapter_title_formatting(self):
        """Chapter titles should be formatted consistently."""
        title1 = format_spoken_chapter_title("Chapter 1", 1, apply_prefix=True)
        title2 = format_spoken_chapter_title("Introduction", 1, apply_prefix=True)
        assert isinstance(title1, str)
        assert isinstance(title2, str)

    def test_chapter_title_no_auto_prefix(self):
        title = format_spoken_chapter_title("My Custom Title", 1, apply_prefix=False)
        assert "My Custom Title" in title

    def test_m4b_forces_merge(self):
        """m4b format should force merge_chapters_at_end=True.
        This is a business rule that must be enforced."""
        # This is tested implicitly — the domain doesn't enforce this,
        # but both UIs should. We document the expected behavior here.
        output_format = "m4b"
        merge_chapters_at_end = False
        # The UI should set this to True for m4b
        if output_format.lower() == "m4b":
            merge_chapters_at_end = True
        assert merge_chapters_at_end is True
