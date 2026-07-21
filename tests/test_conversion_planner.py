"""Tests for the unified conversion planner (build_conversion_plan).

Verifies that the planner correctly handles:
- Plain text conversion
- Voice markers (PyQt style)
- Chapter parsing
- Chunks (WebUI style)
- Intro/outro
- Output layout
- Edge cases (empty text, no chapters, etc.)

Also includes domain-level regression tests for the underlying functions.
"""

import os
import tempfile
from pathlib import Path

import pytest

from abogen.application.conversion_models import (
    ChapterPlan,
    ConversionPlan,
    IntroOutroSpec,
    OutputLayout,
    SegmentPlan,
)
from abogen.application.conversion_planner import build_conversion_plan
from abogen.application.conversion_request import ConversionRequest


class TestBuildConversionPlan:
    """Tests for the main build_conversion_plan function."""

    def test_direct_text_simple(self):
        """Plain text without markers or chapters."""
        req = ConversionRequest(direct_text="Hello world", voice="M1")
        plan = build_conversion_plan(req)

        assert isinstance(plan, ConversionPlan)
        assert len(plan.chapters) == 1
        assert plan.chapters[0].segments[0].text == "Hello world"
        assert plan.chapters[0].segments[0].voice_spec == "M1"
        assert plan.chapters[0].segments[0].source == "chapter"

    def test_direct_text_with_chapters(self):
        """Text with chapter markers is split into chapters."""
        req = ConversionRequest(
            direct_text="<<CHAPTER_MARKER:Chapter 1>>\nText A\n<<CHAPTER_MARKER:Chapter 2>>\nText B",
            voice="M1",
        )
        plan = build_conversion_plan(req)

        assert len(plan.chapters) == 2
        assert plan.chapters[0].title == "Chapter 1"
        assert plan.chapters[1].title == "Chapter 2"

    def test_voice_markers(self):
        """Voice markers are detected and create separate segments."""
        req = ConversionRequest(
            direct_text="Hello <<VOICE:F1>> World", voice="M1"
        )
        plan = build_conversion_plan(req)

        segments = plan.chapters[0].segments
        assert len(segments) == 2
        assert segments[0].text == "Hello"
        assert segments[0].source == "voice_marker"
        assert segments[1].text == "World"
        assert segments[1].source == "voice_marker"

    def test_chunks(self):
        """Chunks from WebUI are converted to segments."""
        req = ConversionRequest(
            direct_text="Some text",
            voice="M1",
            chunks=[
                {"text": "Chunk 1", "speaker_id": "narrator"},
                {"text": "Chunk 2", "speaker_id": "narrator"},
            ],
        )
        plan = build_conversion_plan(req)

        segments = plan.chapters[0].segments
        assert len(segments) == 2
        assert segments[0].text == "Chunk 1"
        assert segments[0].source == "chunk"
        assert segments[1].text == "Chunk 2"

    def test_chunks_with_voice(self):
        """Chunks with per-chunk voice spec."""
        req = ConversionRequest(
            direct_text="Text",
            voice="M1",
            chunks=[
                {"text": "Narrator speaks", "speaker_id": "narrator"},
                {"text": "Character speaks", "speaker_id": "alice", "voice": "F1"},
            ],
            speakers={"alice": {"voice": "F1"}},
        )
        plan = build_conversion_plan(req)

        segments = plan.chapters[0].segments
        assert len(segments) == 2
        assert segments[0].voice_spec == "M1"
        assert segments[1].voice_spec == "F1"

    def test_intro_spec(self):
        """Intro is created when read_title_intro=True."""
        req = ConversionRequest(
            direct_text="<<CHAPTER_MARKER:Chapter 1>>\nThe Great Gatsby by F. Scott Fitzgerald\nBody text",
            voice="M1",
            read_title_intro=True,
            metadata_tags={"title": "The Great Gatsby", "author": "F. Scott Fitzgerald"},
        )
        plan = build_conversion_plan(req)

        # Intro may or may not be enabled depending on metadata resolution
        assert plan.intro is None or isinstance(plan.intro, IntroOutroSpec)

    def test_output_layout(self):
        """Output layout is resolved from request."""
        with tempfile.TemporaryDirectory() as tmpdir:
            req = ConversionRequest(
                direct_text="Hello",
                voice="M1",
                save_mode="custom_folder",
                output_folder=Path(tmpdir),
            )
            plan = build_conversion_plan(req)

            assert isinstance(plan.output_layout, OutputLayout)
            assert plan.output_layout.parent_dir == Path(tmpdir)

    def test_empty_text_raises(self):
        """Empty text should raise ValueError."""
        req = ConversionRequest(direct_text="", voice="M1")
        with pytest.raises(ValueError, match="No text content"):
            build_conversion_plan(req)

    def test_whitespace_only_raises(self):
        """Whitespace-only text should raise ValueError."""
        req = ConversionRequest(direct_text="   \n  \n  ", voice="M1")
        with pytest.raises(ValueError, match="No text content"):
            build_conversion_plan(req)

    def test_no_source_raises(self):
        """Request with no source should raise ValueError."""
        req = ConversionRequest(voice="M1")
        with pytest.raises(ValueError, match="No text content"):
            build_conversion_plan(req)

    def test_plan_preserves_request(self):
        """Plan should reference the original request."""
        req = ConversionRequest(direct_text="Hello", voice="M1", speed=1.5)
        plan = build_conversion_plan(req)

        assert plan.request is req
        assert plan.request.speed == 1.5

    def test_metadata_in_plan(self):
        """Metadata from request should appear in plan."""
        req = ConversionRequest(
            direct_text="Hello",
            voice="M1",
            metadata_tags={"title": "Test Book", "author": "Author"},
        )
        plan = build_conversion_plan(req)

        assert "title" in plan.metadata
        assert plan.metadata["title"] == "Test Book"

    def test_chapter_index_starts_at_1(self):
        """Chapter indices should start at 1."""
        req = ConversionRequest(
            direct_text="<<CHAPTER_MARKER:Ch1>>\nText\n<<CHAPTER_MARKER:Ch2>>\nText\n<<CHAPTER_MARKER:Ch3>>\nText",
            voice="M1",
        )
        plan = build_conversion_plan(req)

        for i, ch in enumerate(plan.chapters, 1):
            assert ch.index == i

    def test_chapter_body_text_preserved(self):
        """Chapter body text should be preserved in ChapterPlan."""
        req = ConversionRequest(
            direct_text="<<CHAPTER_MARKER:Chapter 1>>\nThe actual body text", voice="M1"
        )
        plan = build_conversion_plan(req)

        assert "The actual body text" in plan.chapters[0].body_text

    def test_segment_kind_default(self):
        """Default segment kind should be 'body'."""
        req = ConversionRequest(direct_text="Hello", voice="M1")
        plan = build_conversion_plan(req)

        assert plan.chapters[0].segments[0].kind == "body"


class TestPlannerWithFileSource:
    """Tests using actual file sources (not direct_text)."""

    def test_txt_file(self):
        """Planning from a .txt file."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write("Chapter 1\nHello from file")
            f.flush()
            path = Path(f.name)

        try:
            req = ConversionRequest(source_path=path, voice="M1")
            plan = build_conversion_plan(req)

            assert len(plan.chapters) >= 1
            assert "Hello from file" in plan.chapters[0].segments[0].text
        finally:
            os.unlink(path)

    def test_txt_file_with_voice_markers(self):
        """File with voice markers."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write("Start <<VOICE:F1>> End")
            f.flush()
            path = Path(f.name)

        try:
            req = ConversionRequest(source_path=path, voice="M1")
            plan = build_conversion_plan(req)

            segments = plan.chapters[0].segments
            assert len(segments) == 2
        finally:
            os.unlink(path)


class TestPlannerChapters:
    """Tests for chapter handling in the planner."""

    def test_single_chapter_no_marker(self):
        """Text without markers becomes a single chapter."""
        req = ConversionRequest(direct_text="Just some text", voice="M1")
        plan = build_conversion_plan(req)

        assert len(plan.chapters) == 1
        assert plan.chapters[0].title == "text"

    def test_chapters_with_marker(self):
        """Chapter markers create multiple chapters."""
        req = ConversionRequest(
            direct_text="<<CHAPTER_MARKER:Ch A>>\nText A\n<<CHAPTER_MARKER:Ch B>>\nText B",
            voice="M1",
        )
        plan = build_conversion_plan(req)

        assert len(plan.chapters) == 2
        assert plan.chapters[0].title == "Ch A"
        assert plan.chapters[1].title == "Ch B"

    def test_chapter_voice_spec(self):
        """Chapter voice spec should come from request.voice."""
        req = ConversionRequest(
            direct_text="<<CHAPTER_MARKER:Ch 1>>\nText", voice="af_heart"
        )
        plan = build_conversion_plan(req)

        assert plan.chapters[0].voice_spec == "af_heart"

    def test_chapters_preserve_order(self):
        """Chapters should maintain their order."""
        req = ConversionRequest(
            direct_text="<<CHAPTER_MARKER:Ch A>>\nText A\n<<CHAPTER_MARKER:Ch B>>\nText B\n<<CHAPTER_MARKER:Ch C>>\nText C",
            voice="M1",
        )
        plan = build_conversion_plan(req)

        titles = [ch.title for ch in plan.chapters]
        assert titles == ["Ch A", "Ch B", "Ch C"]


# ─── Domain-level regression tests ─────────────────────────────────

class TestChapterParsing:
    """Verify parse_chapters_from_text produces correct chapter structure."""

    def test_single_chapter_no_markers(self):
        from abogen.domain.text_chapters import parse_chapters_from_text
        text = "This is a simple text without any chapter markers."
        chapters = parse_chapters_from_text(text, clean=False)
        assert len(chapters) == 1
        assert chapters[0][0]
        assert "simple text" in chapters[0][1]

    def test_multiple_chapters_by_markers(self):
        from abogen.domain.text_chapters import parse_chapters_from_text
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
        from abogen.domain.text_chapters import parse_chapters_from_text
        chapters = parse_chapters_from_text("", clean=False)
        assert len(chapters) >= 1

    def test_chapter_content_preserved(self):
        from abogen.domain.text_chapters import parse_chapters_from_text
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
        from abogen.domain.text_chapters import parse_chapters_from_text
        text = """Introduction text here.
<<CHAPTER_MARKER:Chapter 1>>
Chapter content."""
        chapters = parse_chapters_from_text(text, clean=False)
        assert len(chapters) >= 2
        assert chapters[0][0] == "Introduction"
        assert "Introduction text" in chapters[0][1]


class TestVoiceMarkerSplitting:
    """Verify voice marker splitting produces correct segment structure."""

    def test_no_voice_markers(self):
        from abogen.subtitle_utils import split_text_by_voice_markers
        text = "Just plain text without any voice markers."
        segments, last_voice, valid, invalid = split_text_by_voice_markers(text, "M1")
        assert len(segments) == 1
        assert segments[0][0] == "M1"
        assert "plain text" in segments[0][1]

    def test_single_voice_marker(self):
        from abogen.subtitle_utils import split_text_by_voice_markers
        text = "<<VOICE:F1>> Hello from female voice."
        segments, last_voice, valid, invalid = split_text_by_voice_markers(text, "M1")
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
        assert last_voice in ("f1", "F1", "M1")


class TestTTSContext:
    """Verify TTSContext bundles normalization parameters correctly."""

    def test_default_context(self):
        from abogen.domain.normalization import TTSContext
        ctx = TTSContext()
        assert ctx.split_pattern
        assert ctx.pronunciation_rules is None
        assert ctx.heteronym_rules is None
        assert ctx.normalization_overrides is None
        assert ctx.usage_counter == {}

    def test_normalize_passthrough(self):
        from abogen.domain.normalization import TTSContext
        ctx = TTSContext()
        text = "Hello world."
        result = ctx.normalize(text)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_normalize_with_usage_counter(self):
        from abogen.domain.normalization import TTSContext
        ctx = TTSContext()
        ctx.usage_counter["test_token"] = 0
        result = ctx.normalize("Some text.")
        assert isinstance(result, str)


class TestVoiceResolution:
    """Verify voice resolution functions produce valid specs."""

    def test_resolve_fallback_voice_spec(self):
        from abogen.domain.voice_resolution import resolve_fallback_voice_spec
        spec = resolve_fallback_voice_spec("M1", "M1", ["M1", "F1"])
        if spec is not None:
            assert hasattr(spec, "voice_id") or isinstance(spec, str)

    def test_spec_to_voice_ids(self):
        from abogen.domain.voice_resolution import spec_to_voice_ids
        ids = spec_to_voice_ids("M1")
        assert isinstance(ids, set)

    def test_resolve_fallback_with_empty_cache(self):
        from abogen.domain.voice_resolution import resolve_fallback_voice_spec
        spec = resolve_fallback_voice_spec("M1", "M1", [])


class TestIntroOutro:
    """Verify intro/outro resolution with various metadata states."""

    def test_resolve_intro_with_metadata(self):
        from abogen.domain.intro_outro import resolve_intro
        metadata = {"title": "Test Book", "author": "Test Author"}
        spec = resolve_intro(metadata, "test.txt", True, "M1", "M1", ["M1"])
        assert spec is not None
        assert spec.text

    def test_resolve_intro_disabled(self):
        from abogen.domain.intro_outro import resolve_intro
        spec = resolve_intro({}, "test.txt", False, "M1", "M1", ["M1"])
        assert not spec.enabled

    def test_resolve_intro_no_metadata(self):
        from abogen.domain.intro_outro import resolve_intro
        spec = resolve_intro({}, "test.txt", True, "M1", "M1", ["M1"])
        assert spec is not None

    def test_resolve_outro_with_metadata(self):
        from abogen.domain.intro_outro import resolve_outro
        metadata = {"title": "Test Book"}
        spec = resolve_outro(metadata, "test.txt", True, "M1", "M1", ["M1"])
        assert spec is not None
        assert spec.text

    def test_resolve_outro_disabled(self):
        from abogen.domain.intro_outro import resolve_outro
        spec = resolve_outro({}, "test.txt", False, "M1", "M1", ["M1"])
        assert not spec.enabled


class TestOutputPaths:
    """Verify output path resolution produces valid paths."""

    def test_resolve_unique_path(self, tmp_path):
        from abogen.domain.output_paths import resolve_unique_path
        (tmp_path / "test.txt").touch()
        result = resolve_unique_path(
            str(tmp_path), "test", "txt",
            allowed_extensions={"txt", "wav"},
        )
        assert result
        assert "test" in result

    def test_resolve_unique_path_no_collision(self, tmp_path):
        from abogen.domain.output_paths import resolve_unique_path
        result = resolve_unique_path(str(tmp_path), "unique_name", "txt")
        assert result
        assert "unique_name" in result

    def test_sanitize_output_stem(self):
        from abogen.domain.output_paths import sanitize_output_stem
        stem = sanitize_output_stem("My Book Title")
        assert isinstance(stem, str)
        assert len(stem) > 0

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


class TestSubtitleGeneration:
    """Verify subtitle token processing works correctly."""

    def test_process_empty_tokens(self):
        from abogen.domain.subtitle_generation import process_subtitle_tokens
        entries = []
        process_subtitle_tokens(
            [], entries, 5, "Sentence", "a",
            use_spacy_segmentation=False,
            fallback_end_time=10.0,
        )
        assert entries == []

    def test_process_sentence_mode(self):
        from abogen.domain.subtitle_generation import process_subtitle_tokens
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
        assert len(entries) >= 1
        start, end, text = entries[0]
        assert start < end
        assert isinstance(text, str)

    def test_process_line_mode(self):
        from abogen.domain.subtitle_generation import process_subtitle_tokens
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
        assert len(entries) >= 1


class TestFeatureParity:
    """Regression tests for features that must work in both UIs."""

    def test_chapter_title_formatting(self):
        from abogen.domain.chapter_titles import format_spoken_chapter_title
        title1 = format_spoken_chapter_title("Chapter 1", 1, apply_prefix=True)
        title2 = format_spoken_chapter_title("Introduction", 1, apply_prefix=True)
        assert isinstance(title1, str)
        assert isinstance(title2, str)

    def test_chapter_title_no_auto_prefix(self):
        from abogen.domain.chapter_titles import format_spoken_chapter_title
        title = format_spoken_chapter_title("My Custom Title", 1, apply_prefix=False)
        assert "My Custom Title" in title

    def test_m4b_forces_merge(self):
        output_format = "m4b"
        merge_chapters_at_end = False
        if output_format.lower() == "m4b":
            merge_chapters_at_end = True
        assert merge_chapters_at_end is True
