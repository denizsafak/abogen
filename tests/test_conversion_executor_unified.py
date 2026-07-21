"""Tests for the unified conversion executor (execute_conversion).

Uses fake/mock objects for ports (events, pipeline_provider, voice_resolver)
to test the executor without real TTS or audio I/O.
"""

import tempfile
from pathlib import Path
from typing import Any, List, Optional
from unittest.mock import MagicMock

import numpy as np
import pytest

from abogen.application.conversion_executor import execute_conversion
from abogen.application.conversion_models import (
    ChapterPlan,
    ConversionPlan,
    IntroOutroSpec,
    OutputLayout,
    SegmentPlan,
)
from abogen.application.conversion_ports import ResolvedVoice
from abogen.application.conversion_request import ConversionRequest
from abogen.domain.normalization import TTSContext


# ─── Fake implementations ──────────────────────────────────────────


class FakeAudioSink:
    """Fake audio sink that collects written audio data."""

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


class FakeSubtitleWriter:
    """Fake subtitle writer that collects entries."""

    def __init__(self, path: Optional[Path] = None):
        self.path = path or Path("/fake/output.srt")
        self.entries = []
        self.closed = False

    def open(self) -> None:
        pass

    def write_entry(self, start: float, end: float, text: str) -> None:
        self.entries.append((start, end, text))

    def close(self) -> None:
        self.closed = True


class FakeBackend:
    """Fake TTS backend that returns silent audio segments."""

    def __init__(self):
        self.synthesized: List[str] = []

    def __call__(self, text: str, *, voice: Any, speed: float = 1.0, split_pattern: str = "") -> List:
        """Return fake TTS segments."""
        self.synthesized.append(text)

        # Create a fake segment object
        class FakeSegment:
            def __init__(self, text: str):
                self.graphemes = text
                self.audio = np.zeros(2400, dtype=np.float32)  # 0.1s at 24kHz
                self.tokens = []

        return [FakeSegment(text)]


class FakeEvents:
    """Fake conversion events that collect logs and progress."""

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
    """Fake pipeline provider that returns FakeBackend."""

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
    """Fake voice resolver that returns ResolvedVoice objects."""

    def __init__(self):
        self.resolved_specs = []

    def resolve(self, voice_spec: str) -> ResolvedVoice:
        self.resolved_specs.append(voice_spec)
        return ResolvedVoice(
            provider="kokoro",
            resolved_spec=voice_spec,
            voice=voice_spec,  # Use spec as voice name
            speed=1.0,
            supertonic_steps=5,
        )


# ─── Tests ──────────────────────────────────────────────────────────


class TestExecuteConversion:
    """Tests for the main execute_conversion function."""

    def test_simple_text_conversion(self):
        """Simple text conversion without chapters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            req = ConversionRequest(
                direct_text="Hello world",
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
                        body_text="Hello world",
                        segments=[
                            SegmentPlan(
                                text="Hello world",
                                voice_spec="M1",
                                kind="body",
                                source="chapter",
                            )
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

            result = execute_conversion(
                plan, events, pipeline, resolver, tts_context
            )

            assert result is not None
            assert result.audio_path is not None
            assert result.audio_path.exists()

    def test_multi_chapter_conversion(self):
        """Multi-chapter conversion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            req = ConversionRequest(
                direct_text="Text",
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
                        body_text="First chapter text",
                        segments=[
                            SegmentPlan(
                                text="First chapter text",
                                voice_spec="M1",
                                kind="body",
                                source="chapter",
                            )
                        ],
                        voice_spec="M1",
                    ),
                    ChapterPlan(
                        index=2,
                        title="Chapter 2",
                        original_title="Chapter 2",
                        body_text="Second chapter text",
                        segments=[
                            SegmentPlan(
                                text="Second chapter text",
                                voice_spec="M1",
                                kind="body",
                                source="chapter",
                            )
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

            result = execute_conversion(
                plan, events, pipeline, resolver, tts_context
            )

            assert result.total_chapters == 2
            assert len(result.chapter_paths) == 2

    def test_voice_markers(self):
        """Conversion with voice markers creates separate segments."""
        with tempfile.TemporaryDirectory() as tmpdir:
            req = ConversionRequest(
                direct_text="Text",
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
                        body_text="Hello World",
                        segments=[
                            SegmentPlan(
                                text="Hello",
                                voice_spec="M1",
                                kind="body",
                                source="voice_marker",
                            ),
                            SegmentPlan(
                                text="World",
                                voice_spec="F1",
                                kind="body",
                                source="voice_marker",
                            ),
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

            result = execute_conversion(
                plan, events, pipeline, resolver, tts_context
            )

            assert result is not None
            assert len(result.chunk_markers) == 2

    def test_intro_outro(self):
        """Conversion with intro and outro."""
        with tempfile.TemporaryDirectory() as tmpdir:
            req = ConversionRequest(
                direct_text="Text",
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
                        body_text="Body text",
                        segments=[
                            SegmentPlan(
                                text="Body text",
                                voice_spec="M1",
                                kind="body",
                                source="chapter",
                            )
                        ],
                        voice_spec="M1",
                    )
                ],
                intro=IntroOutroSpec(
                    enabled=True,
                    text="Book intro text",
                    voice_spec="M1",
                    kind="intro",
                ),
                outro=IntroOutroSpec(
                    enabled=True,
                    text="Book outro text",
                    voice_spec="M1",
                    kind="outro",
                ),
                output_layout=OutputLayout(
                    parent_dir=Path(tmpdir),
                    audio_dir=Path(tmpdir),
                ),
            )

            events = FakeEvents()
            pipeline = FakePipelineProvider()
            resolver = FakeVoiceResolver()
            tts_context = TTSContext()

            result = execute_conversion(
                plan, events, pipeline, resolver, tts_context
            )

            assert result is not None
            # Check that intro/outro were logged
            log_messages = [msg for msg, _ in events.logs]
            assert any("Title intro" in msg for msg in log_messages)
            assert any("Closing outro" in msg for msg in log_messages)

    def test_cancellation(self):
        """Conversion can be cancelled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            req = ConversionRequest(
                direct_text="Text",
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
                        body_text="Body text",
                        segments=[
                            SegmentPlan(
                                text="Body text",
                                voice_spec="M1",
                                kind="body",
                                source="chapter",
                            )
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
            events.cancelled = True  # Set cancellation
            pipeline = FakePipelineProvider()
            resolver = FakeVoiceResolver()
            tts_context = TTSContext()

            # Should raise RuntimeError when cancelled
            with pytest.raises(RuntimeError, match="Conversion cancelled"):
                execute_conversion(
                    plan, events, pipeline, resolver, tts_context
                )

    def test_progress_reporting(self):
        """Progress is reported during conversion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            req = ConversionRequest(
                direct_text="Hello world",
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
                        body_text="Hello world",
                        segments=[
                            SegmentPlan(
                                text="Hello world",
                                voice_spec="M1",
                                kind="body",
                                source="chapter",
                            )
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

            result = execute_conversion(
                plan, events, pipeline, resolver, tts_context
            )

            # Progress should have been reported
            assert len(events.progress_calls) > 0

    def test_metadata_preserved(self):
        """Metadata from plan is preserved in result."""
        with tempfile.TemporaryDirectory() as tmpdir:
            req = ConversionRequest(
                direct_text="Text",
                voice="M1",
                save_mode="custom_folder",
                output_folder=Path(tmpdir),
            )
            plan = ConversionPlan(
                request=req,
                metadata={"title": "Test Book", "author": "Author"},
                chapters=[
                    ChapterPlan(
                        index=1,
                        title="text",
                        original_title="text",
                        body_text="Text",
                        segments=[
                            SegmentPlan(
                                text="Text",
                                voice_spec="M1",
                                kind="body",
                                source="chapter",
                            )
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

            result = execute_conversion(
                plan, events, pipeline, resolver, tts_context
            )

            assert result.metadata["title"] == "Test Book"
            assert result.metadata["author"] == "Author"
