"""Tests for conversion_service.py, output_layout_service.py, and executor gaps.

Covers the remaining untested code in the application layer.
"""

import tempfile
from pathlib import Path
from typing import Any, List, Optional
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from abogen.application.conversion_request import ConversionRequest
from abogen.application.conversion_models import (
    ChapterPlan,
    ConversionPlan,
    IntroOutroSpec,
    OutputLayout,
    SegmentPlan,
)
from abogen.application.conversion_ports import ResolvedVoice
from abogen.domain.normalization import TTSContext


# ─── Fake implementations (shared with executor tests) ─────────────


class FakeAudioSink:
    def __init__(self):
        self.written: List[np.ndarray] = []
        self.closed = False

    def write(self, audio: np.ndarray) -> None:
        self.written.append(audio)

    def close(self) -> None:
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class FakeBackend:
    def __init__(self):
        self.synthesized: List[str] = []

    def __call__(self, text: str, *, voice: Any, speed: float = 1.0, split_pattern: str = "") -> List:
        self.synthesized.append(text)

        class FakeSegment:
            def __init__(self, text: str):
                self.graphemes = text
                self.audio = np.zeros(2400, dtype=np.float32)
                self.tokens = []

        return [FakeSegment(text)]


class FakeEvents:
    def __init__(self):
        self.logs = []
        self.progress_calls = []
        self.cancelled = False

    def log(self, message: str, level: str = "info") -> None:
        self.logs.append((message, level))

    def progress(self, pct: int, etr: str) -> None:
        self.progress_calls.append((pct, etr))

    def check_cancelled(self) -> None:
        if self.cancelled:
            raise RuntimeError("Conversion cancelled")


class FakePipelineProvider:
    def __init__(self):
        self.backends = {}

    def get(self, provider: str, language: str, use_gpu: bool) -> FakeBackend:
        key = f"{provider}:{language}"
        if key not in self.backends:
            self.backends[key] = FakeBackend()
        return self.backends[key]

    def dispose_all(self) -> None:
        self.backends.clear()


class FakeVoiceResolver:
    def __init__(self):
        self.resolved_specs = []

    def resolve(self, voice_spec: str) -> ResolvedVoice:
        self.resolved_specs.append(voice_spec)
        return ResolvedVoice(
            provider="kokoro",
            resolved_spec=voice_spec,
            voice=voice_spec,
            speed=1.0,
            supertonic_steps=5,
        )


# ─── Tests for conversion_service.py ───────────────────────────────


class TestConversionService:
    """Tests for the ConversionService.run_conversion function."""

    def test_simple_conversion(self):
        """Simple text conversion through the service."""
        from abogen.application.conversion_service import run_conversion

        with tempfile.TemporaryDirectory() as tmpdir:
            req = ConversionRequest(
                direct_text="Hello world",
                voice="M1",
                save_mode="custom_folder",
                output_folder=Path(tmpdir),
            )
            events = FakeEvents()
            pipeline = FakePipelineProvider()
            resolver = FakeVoiceResolver()

            result = run_conversion(req, events, pipeline, resolver)

            assert result is not None
            assert result.audio_path is not None
            assert result.audio_path.exists()

    def test_service_logs_pipeline_preparation(self):
        """Service logs pipeline preparation step."""
        from abogen.application.conversion_service import run_conversion

        with tempfile.TemporaryDirectory() as tmpdir:
            req = ConversionRequest(
                direct_text="Hello",
                voice="M1",
                save_mode="custom_folder",
                output_folder=Path(tmpdir),
            )
            events = FakeEvents()
            pipeline = FakePipelineProvider()
            resolver = FakeVoiceResolver()

            result = run_conversion(req, events, pipeline, resolver)

            log_messages = [msg for msg, _ in events.logs]
            assert any("Preparing conversion pipeline" in msg for msg in log_messages)
            assert any("Building conversion plan" in msg for msg in log_messages)
            assert any("Starting conversion" in msg for msg in log_messages)
            assert any("Conversion complete" in msg for msg in log_messages)

    def test_service_handles_cancellation(self):
        """Service propagates cancellation from events."""
        from abogen.application.conversion_service import run_conversion

        with tempfile.TemporaryDirectory() as tmpdir:
            req = ConversionRequest(
                direct_text="Hello",
                voice="M1",
                save_mode="custom_folder",
                output_folder=Path(tmpdir),
            )
            events = FakeEvents()
            events.cancelled = True
            pipeline = FakePipelineProvider()
            resolver = FakeVoiceResolver()

            with pytest.raises(RuntimeError, match="Conversion cancelled"):
                run_conversion(req, events, pipeline, resolver)

    def test_service_handles_empty_text(self):
        """Service raises ValueError for empty text."""
        from abogen.application.conversion_service import run_conversion

        req = ConversionRequest(direct_text="", voice="M1")
        events = FakeEvents()
        pipeline = FakePipelineProvider()
        resolver = FakeVoiceResolver()

        with pytest.raises(ValueError, match="No text content"):
            run_conversion(req, events, pipeline, resolver)

    def test_service_multi_chapter(self):
        """Service handles multi-chapter conversion."""
        from abogen.application.conversion_service import run_conversion

        with tempfile.TemporaryDirectory() as tmpdir:
            req = ConversionRequest(
                direct_text="<<CHAPTER_MARKER:Ch1>>\nText A\n<<CHAPTER_MARKER:Ch2>>\nText B",
                voice="M1",
                save_mode="custom_folder",
                output_folder=Path(tmpdir),
            )
            events = FakeEvents()
            pipeline = FakePipelineProvider()
            resolver = FakeVoiceResolver()

            result = run_conversion(req, events, pipeline, resolver)

            assert result.total_chapters == 2

    def test_service_with_intro_outro(self):
        """Service handles intro/outro."""
        from abogen.application.conversion_service import run_conversion

        with tempfile.TemporaryDirectory() as tmpdir:
            req = ConversionRequest(
                direct_text="Body text",
                voice="M1",
                save_mode="custom_folder",
                output_folder=Path(tmpdir),
                read_title_intro=True,
                read_closing_outro=True,
                metadata_tags={"title": "Test Book", "author": "Author"},
            )
            events = FakeEvents()
            pipeline = FakePipelineProvider()
            resolver = FakeVoiceResolver()

            result = run_conversion(req, events, pipeline, resolver)

            assert result is not None

    def test_service_error_logs_failure(self):
        """Service logs error when conversion fails."""
        from abogen.application.conversion_service import run_conversion

        req = ConversionRequest(direct_text="Hello", voice="M1")
        events = FakeEvents()
        pipeline = FakePipelineProvider()
        resolver = FakeVoiceResolver()

        # Mock build_conversion_plan to raise an error
        with patch("abogen.application.conversion_service.build_conversion_plan", side_effect=RuntimeError("Test error")):
            with pytest.raises(RuntimeError, match="Test error"):
                run_conversion(req, events, pipeline, resolver)

            log_messages = [msg for msg, _ in events.logs]
            assert any("Conversion failed" in msg for msg in log_messages)


# ─── Tests for output_layout_service.py ─────────────────────────────


class TestOutputLayoutService:
    """Tests for the output_layout_service module."""

    def test_resolve_output_layout_custom_folder(self):
        """Output layout with custom folder."""
        from abogen.application.output_layout_service import resolve_output_layout

        with tempfile.TemporaryDirectory() as tmpdir:
            req = ConversionRequest(
                direct_text="Hello",
                voice="M1",
                save_mode="custom_folder",
                output_folder=Path(tmpdir),
            )
            layout = resolve_output_layout(req)

            assert layout.parent_dir == Path(tmpdir)
            assert layout.audio_dir == Path(tmpdir)

    def test_resolve_output_layout_source_path(self):
        """Output layout from source path."""
        from abogen.application.output_layout_service import resolve_output_layout

        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "test.txt"
            source.write_text("Hello")
            req = ConversionRequest(
                source_path=source,
                voice="M1",
                save_mode="save_next_to_input",
            )
            layout = resolve_output_layout(req)

            assert layout.parent_dir == Path(tmpdir)

    def test_resolve_output_layout_project(self):
        """Output layout with save_as_project."""
        from abogen.application.output_layout_service import resolve_output_layout

        with tempfile.TemporaryDirectory() as tmpdir:
            req = ConversionRequest(
                direct_text="Hello",
                voice="M1",
                save_mode="custom_folder",
                output_folder=Path(tmpdir),
                save_as_project=True,
                original_filename="test.wav",
            )
            layout = resolve_output_layout(req)

            assert layout.project_root is not None
            assert layout.audio_dir is not None

    def test_resolve_merged_path(self):
        """Resolve merged output path."""
        from abogen.application.output_layout_service import resolve_merged_path

        with tempfile.TemporaryDirectory() as tmpdir:
            layout = OutputLayout(
                parent_dir=Path(tmpdir),
                audio_dir=Path(tmpdir),
            )
            req = ConversionRequest(
                direct_text="Hello",
                voice="M1",
                original_filename="book.wav",
                output_format="wav",
            )
            path = resolve_merged_path(layout, req)

            assert path.name == "book.wav"
            assert path.parent == Path(tmpdir)

    def test_resolve_chapter_path(self):
        """Resolve chapter output path."""
        from abogen.application.output_layout_service import resolve_chapter_path

        with tempfile.TemporaryDirectory() as tmpdir:
            layout = OutputLayout(
                parent_dir=Path(tmpdir),
                audio_dir=Path(tmpdir),
            )
            req = ConversionRequest(
                direct_text="Hello",
                voice="M1",
                separate_chapters_format="wav",
            )
            path = resolve_chapter_path(layout, req, "Chapter 1", 1)

            assert "01" in path.name
            assert path.suffix == ".wav"

    def test_resolve_chapter_path_empty_title(self):
        """Resolve chapter path with empty title."""
        from abogen.application.output_layout_service import resolve_chapter_path

        with tempfile.TemporaryDirectory() as tmpdir:
            layout = OutputLayout(
                parent_dir=Path(tmpdir),
                audio_dir=Path(tmpdir),
            )
            req = ConversionRequest(
                direct_text="Hello",
                voice="M1",
                separate_chapters_format="wav",
            )
            path = resolve_chapter_path(layout, req, "", 3)

            assert "chapter_3" in path.name

    def test_should_merge_output_m4b(self):
        """m4b format forces merge."""
        from abogen.application.output_layout_service import should_merge_output

        req = ConversionRequest(
            direct_text="Hello",
            voice="M1",
            output_format="m4b",
            merge_chapters_at_end=False,
        )
        assert should_merge_output(req) is True

    def test_should_merge_output_no_separate(self):
        """No separate chapters means merge."""
        from abogen.application.output_layout_service import should_merge_output

        req = ConversionRequest(
            direct_text="Hello",
            voice="M1",
            save_chapters_separately=False,
        )
        assert should_merge_output(req) is True

    def test_should_merge_output_separate_and_merge(self):
        """Separate chapters + merge_at_end means merge."""
        from abogen.application.output_layout_service import should_merge_output

        req = ConversionRequest(
            direct_text="Hello",
            voice="M1",
            save_chapters_separately=True,
            merge_chapters_at_end=True,
        )
        assert should_merge_output(req) is True

    def test_should_merge_output_separate_no_merge(self):
        """Separate chapters + no merge_at_end means no merge."""
        from abogen.application.output_layout_service import should_merge_output

        req = ConversionRequest(
            direct_text="Hello",
            voice="M1",
            save_chapters_separately=True,
            merge_chapters_at_end=False,
        )
        assert should_merge_output(req) is False


# ─── Tests for executor gaps ────────────────────────────────────────


class TestExecutorGaps:
    """Tests for uncovered executor branches."""

    def test_executor_no_layout_raises(self):
        """Executor raises ValueError without output_layout."""
        from abogen.application.conversion_executor import execute_conversion

        req = ConversionRequest(direct_text="Hello", voice="M1")
        plan = ConversionPlan(
            request=req,
            metadata={},
            chapters=[],
            output_layout=None,
        )
        events = FakeEvents()
        pipeline = FakePipelineProvider()
        resolver = FakeVoiceResolver()
        tts_context = TTSContext()

        with pytest.raises(ValueError, match="output_layout"):
            execute_conversion(plan, events, pipeline, resolver, tts_context)

    def test_executor_m4b_forces_merge(self):
        """Executor forces merge for m4b format."""
        from abogen.application.conversion_executor import execute_conversion

        with tempfile.TemporaryDirectory() as tmpdir:
            req = ConversionRequest(
                direct_text="Hello",
                voice="M1",
                save_mode="custom_folder",
                output_folder=Path(tmpdir),
                output_format="m4b",
                save_chapters_separately=True,
                merge_chapters_at_end=False,
            )
            plan = ConversionPlan(
                request=req,
                metadata={},
                chapters=[
                    ChapterPlan(
                        index=1,
                        title="text",
                        original_title="text",
                        body_text="Hello",
                        segments=[
                            SegmentPlan(text="Hello", voice_spec="M1", kind="body", source="chapter")
                        ],
                        voice_spec="M1",
                    )
                ],
                output_layout=OutputLayout(
                    parent_dir=Path(tmpdir),
                    audio_dir=Path(tmpdir),
                ),
            )

            events = FakeEvents()
            pipeline = FakePipelineProvider()
            resolver = FakeVoiceResolver()
            tts_context = TTSContext()

            result = execute_conversion(plan, events, pipeline, resolver, tts_context)

            assert result.audio_path is not None
            assert result.audio_path.suffix == ".m4b"

    def test_executor_separate_chapters(self):
        """Executor creates separate chapter files."""
        from abogen.application.conversion_executor import execute_conversion

        with tempfile.TemporaryDirectory() as tmpdir:
            req = ConversionRequest(
                direct_text="Hello",
                voice="M1",
                save_mode="custom_folder",
                output_folder=Path(tmpdir),
                save_chapters_separately=True,
                merge_chapters_at_end=True,
            )
            plan = ConversionPlan(
                request=req,
                metadata={},
                chapters=[
                    ChapterPlan(
                        index=1,
                        title="Chapter 1",
                        original_title="Chapter 1",
                        body_text="Text A",
                        segments=[
                            SegmentPlan(text="Text A", voice_spec="M1", kind="body", source="chapter")
                        ],
                        voice_spec="M1",
                    ),
                    ChapterPlan(
                        index=2,
                        title="Chapter 2",
                        original_title="Chapter 2",
                        body_text="Text B",
                        segments=[
                            SegmentPlan(text="Text B", voice_spec="M1", kind="body", source="chapter")
                        ],
                        voice_spec="M1",
                    ),
                ],
                output_layout=OutputLayout(
                    parent_dir=Path(tmpdir),
                    audio_dir=Path(tmpdir),
                ),
            )

            events = FakeEvents()
            pipeline = FakePipelineProvider()
            resolver = FakeVoiceResolver()
            tts_context = TTSContext()

            result = execute_conversion(plan, events, pipeline, resolver, tts_context)

            assert len(result.chapter_paths) == 2

    def test_executor_no_intro_outro(self):
        """Executor works without intro/outro."""
        from abogen.application.conversion_executor import execute_conversion

        with tempfile.TemporaryDirectory() as tmpdir:
            req = ConversionRequest(
                direct_text="Hello",
                voice="M1",
                save_mode="custom_folder",
                output_folder=Path(tmpdir),
            )
            plan = ConversionPlan(
                request=req,
                metadata={},
                chapters=[
                    ChapterPlan(
                        index=1,
                        title="text",
                        original_title="text",
                        body_text="Hello",
                        segments=[
                            SegmentPlan(text="Hello", voice_spec="M1", kind="body", source="chapter")
                        ],
                        voice_spec="M1",
                    )
                ],
                intro=None,
                outro=None,
                output_layout=OutputLayout(
                    parent_dir=Path(tmpdir),
                    audio_dir=Path(tmpdir),
                ),
            )

            events = FakeEvents()
            pipeline = FakePipelineProvider()
            resolver = FakeVoiceResolver()
            tts_context = TTSContext()

            result = execute_conversion(plan, events, pipeline, resolver, tts_context)

            assert result is not None
            log_messages = [msg for msg, _ in events.logs]
            assert not any("Title intro" in msg for msg in log_messages)
            assert not any("Closing outro" in msg for msg in log_messages)

    def test_executor_voice_fallback_on_error(self):
        """Executor falls back to base voice on resolution error."""
        from abogen.application.conversion_executor import execute_conversion

        class FailingVoiceResolver:
            def resolve(self, voice_spec: str) -> ResolvedVoice:
                if voice_spec == "F1":
                    raise ValueError("Voice not found")
                return ResolvedVoice(
                    provider="kokoro",
                    resolved_spec=voice_spec,
                    voice=voice_spec,
                    speed=1.0,
                    supertonic_steps=5,
                )

        with tempfile.TemporaryDirectory() as tmpdir:
            req = ConversionRequest(
                direct_text="Hello",
                voice="M1",
                save_mode="custom_folder",
                output_folder=Path(tmpdir),
            )
            plan = ConversionPlan(
                request=req,
                metadata={},
                chapters=[
                    ChapterPlan(
                        index=1,
                        title="text",
                        original_title="text",
                        body_text="Hello",
                        segments=[
                            SegmentPlan(text="Hello", voice_spec="M1", kind="body", source="chapter")
                        ],
                        voice_spec="M1",
                    )
                ],
                output_layout=OutputLayout(
                    parent_dir=Path(tmpdir),
                    audio_dir=Path(tmpdir),
                ),
            )

            events = FakeEvents()
            pipeline = FakePipelineProvider()
            resolver = FailingVoiceResolver()
            tts_context = TTSContext()

            result = execute_conversion(plan, events, pipeline, resolver, tts_context)

            assert result is not None

    def test_executor_silence_between_chapters(self):
        """Executor adds silence between chapters."""
        from abogen.application.conversion_executor import execute_conversion

        with tempfile.TemporaryDirectory() as tmpdir:
            req = ConversionRequest(
                direct_text="Hello",
                voice="M1",
                save_mode="custom_folder",
                output_folder=Path(tmpdir),
                silence_between_chapters=1.0,
            )
            plan = ConversionPlan(
                request=req,
                metadata={},
                chapters=[
                    ChapterPlan(
                        index=1,
                        title="Ch1",
                        original_title="Ch1",
                        body_text="Text A",
                        segments=[
                            SegmentPlan(text="Text A", voice_spec="M1", kind="body", source="chapter")
                        ],
                        voice_spec="M1",
                    ),
                    ChapterPlan(
                        index=2,
                        title="Ch2",
                        original_title="Ch2",
                        body_text="Text B",
                        segments=[
                            SegmentPlan(text="Text B", voice_spec="M1", kind="body", source="chapter")
                        ],
                        voice_spec="M1",
                    ),
                ],
                output_layout=OutputLayout(
                    parent_dir=Path(tmpdir),
                    audio_dir=Path(tmpdir),
                ),
            )

            events = FakeEvents()
            pipeline = FakePipelineProvider()
            resolver = FakeVoiceResolver()
            tts_context = TTSContext()

            result = execute_conversion(plan, events, pipeline, resolver, tts_context)

            assert result is not None
            # Check that audio was written (silence + speech)
            assert len(pipeline.backends) > 0
