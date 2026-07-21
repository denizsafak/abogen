"""Tests for conversion adapters (WebUI + PyQt).

Covers field mapping, event bridging, voice resolution, and cancellation behavior.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from abogen.application.conversion_request import ConversionRequest
from abogen.application.conversion_ports import ResolvedVoice


# ─── WebUI adapter tests ───────────────────────────────────────────


class TestWebUIAdapter:
    """Test WebUI conversion adapter field mapping."""

    def _make_job(self, **overrides):
        """Create a mock WebUI Job with default values."""
        defaults = dict(
            stored_path="/tmp/test.epub",
            original_filename="test.epub",
            language="a",
            tts_provider="kokoro",
            voice="M1",
            voice_profile=None,
            speed=1.0,
            use_gpu=False,
            supertonic_total_steps=5,
            output_format="wav",
            subtitle_mode="Disabled",
            subtitle_format="srt",
            max_subtitle_words=50,
            save_mode="save_next_to_input",
            output_folder=None,
            save_chapters_separately=False,
            merge_chapters_at_end=True,
            separate_chapters_format="wav",
            save_as_project=False,
            silence_between_chapters=2.0,
            chapter_intro_delay=0.0,
            replace_single_newlines=False,
            read_title_intro=False,
            read_closing_outro=False,
            auto_prefix_chapter_titles=True,
            normalize_chapter_opening_caps=False,
            pronunciation_overrides=[],
            manual_overrides=[],
            heteronym_overrides=[],
            normalization_overrides={},
            chapters=[],
            chunks=[],
            chunk_level="paragraph",
            speaker_mode="single",
            speakers={},
            metadata_tags={},
            cover_image_path=None,
            cover_image_mime=None,
            generate_epub3=False,
            cancel_requested=False,
        )
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def test_basic_field_mapping(self):
        from abogen.webui.conversion_adapter import build_conversion_request_from_job

        job = self._make_job()
        req = build_conversion_request_from_job(job)

        assert isinstance(req, ConversionRequest)
        assert req.source_path == Path("/tmp/test.epub")
        assert req.original_filename == "test.epub"
        assert req.language == "a"
        assert req.voice == "M1"
        assert req.speed == 1.0
        assert req.output_format == "wav"

    def test_optional_fields_mapped(self):
        from abogen.webui.conversion_adapter import build_conversion_request_from_job

        job = self._make_job(
            voice_profile="custom_profile",
            output_folder="/output",
            cover_image_path="/cover.jpg",
            cover_image_mime="image/jpeg",
            metadata_tags={"title": "Test"},
        )
        req = build_conversion_request_from_job(job)

        assert req.voice_profile == "custom_profile"
        assert req.output_folder == Path("/output")
        assert req.cover_image_path == Path("/cover.jpg")
        assert req.cover_image_mime == "image/jpeg"
        assert req.metadata_tags == {"title": "Test"}

    def test_none_paths_result_in_none(self):
        from abogen.webui.conversion_adapter import build_conversion_request_from_job

        job = self._make_job(
            stored_path=None,
            output_folder=None,
            cover_image_path=None,
        )
        req = build_conversion_request_from_job(job)

        assert req.source_path is None
        assert req.output_folder is None
        assert req.cover_image_path is None

    def test_chapter_overrides_mapped(self):
        from abogen.webui.conversion_adapter import build_conversion_request_from_job

        chapters = [{"title": "Ch1", "voice": "F1"}]
        job = self._make_job(chapters=chapters)
        req = build_conversion_request_from_job(job)

        assert req.chapter_overrides == chapters

    def test_chunks_mapped(self):
        from abogen.webui.conversion_adapter import build_conversion_request_from_job

        chunks = [{"text": "Hello", "speaker": "A"}]
        job = self._make_job(chunks=chunks)
        req = build_conversion_request_from_job(job)

        assert req.chunks == chunks

    def test_pronunciation_overrides_mapped(self):
        from abogen.webui.conversion_adapter import build_conversion_request_from_job

        job = self._make_job(
            pronunciation_overrides=["word=pron"],
            manual_overrides=["manual=override"],
            heteronym_overrides=["read=reed"],
        )
        req = build_conversion_request_from_job(job)

        assert req.pronunciation_overrides == ["word=pron"]
        assert req.manual_overrides == ["manual=override"]
        assert req.heteronym_overrides == ["read=reed"]

    def test_none_defaults_handled(self):
        from abogen.webui.conversion_adapter import build_conversion_request_from_job

        job = self._make_job(
            language=None,
            voice=None,
            speed=None,
            output_format=None,
            subtitle_mode=None,
            save_mode=None,
            silence_between_chapters=None,
            chapter_intro_delay=None,
            supertonic_total_steps=None,
            max_subtitle_words=None,
        )
        req = build_conversion_request_from_job(job)

        assert req.language == "a"
        assert req.voice == "M1"
        assert req.speed == 1.0
        assert req.output_format == "wav"
        assert req.subtitle_mode == "Disabled"
        assert req.save_mode == "save_next_to_input"
        assert req.silence_between_chapters == 2.0
        assert req.chapter_intro_delay == 0.0
        assert req.supertonic_total_steps == 5
        assert req.max_subtitle_words == 50


class TestWebUIEvents:
    """Test WebUI ConversionEvents implementation."""

    def test_log_calls_add_log(self):
        from abogen.webui.conversion_adapter import WebJobEvents

        job = SimpleNamespace(add_log=MagicMock())
        events = WebJobEvents(job)
        events.log("test message", level="info")

        job.add_log.assert_called_once_with("test message", level="info")

    def test_progress_updates_job(self):
        from abogen.webui.conversion_adapter import WebJobEvents

        job = SimpleNamespace(progress=0.0, etr_str="")
        events = WebJobEvents(job)
        events.progress(50, "2m 30s")

        assert job.progress == 0.5
        assert job.etr_str == "2m 30s"

    def test_check_cancelled_raises(self):
        from abogen.webui.conversion_adapter import ConversionCancelled, WebJobEvents

        job = SimpleNamespace(cancel_requested=True)
        events = WebJobEvents(job)

        with pytest.raises(ConversionCancelled):
            events.check_cancelled()

    def test_check_not_cancelled_passes(self):
        from abogen.webui.conversion_adapter import WebJobEvents

        job = SimpleNamespace(cancel_requested=False)
        events = WebJobEvents(job)

        events.check_cancelled()  # Should not raise


class TestWebUIPipelineProvider:
    """Test WebUI PipelineProvider implementation."""

    def test_get_returns_backend(self):
        from abogen.webui.conversion_adapter import WebPipelineProvider

        backend = MagicMock()
        pool = SimpleNamespace(get=MagicMock(return_value=backend))
        provider = WebPipelineProvider(pool)

        result = provider.get("kokoro", "a", False)

        assert result is backend
        pool.get.assert_called_once_with("kokoro", "a", False)


class TestWebUIVoiceResolver:
    """Test WebUI VoiceResolver implementation."""

    def test_resolve_returns_resolved_voice(self):
        from abogen.webui.conversion_adapter import WebVoiceResolver

        def resolve_fn(spec):
            return ("kokoro", spec, "M1", 1.0, 5)

        resolver = WebVoiceResolver(resolve_fn)
        result = resolver.resolve("M1")

        assert isinstance(result, ResolvedVoice)
        assert result.provider == "kokoro"
        assert result.voice == "M1"
        assert result.speed == 1.0
        assert result.supertonic_steps == 5

    def test_resolve_none_speed_defaults(self):
        from abogen.webui.conversion_adapter import WebVoiceResolver

        def resolve_fn(spec):
            return ("kokoro", spec, "M1", None, None)

        resolver = WebVoiceResolver(resolve_fn)
        result = resolver.resolve("M1")

        assert result.speed == 1.0
        assert result.supertonic_steps == 5


# ─── PyQt adapter tests ────────────────────────────────────────────


class TestPyQtAdapter:
    """Test PyQt conversion adapter field mapping."""

    def _make_thread(self, **overrides):
        """Create a mock ConversionThread with default values."""
        defaults = dict(
            file_name="/tmp/test.epub",
            lang_code="a",
            voice="M1",
            voice_profile=None,
            speed=1.0,
            use_gpu=False,
            supertonic_total_steps=5,
            output_format="wav",
            subtitle_mode="Disabled",
            subtitle_format="srt",
            max_subtitle_words=50,
            save_option="save_next_to_input",
            output_folder=None,
            save_chapters_separately=False,
            merge_chapters_at_end=True,
            separate_chapters_format="wav",
            save_as_project=False,
            silence_duration=2.0,
            chapter_intro_delay=0.0,
            replace_single_newlines=False,
            read_title_intro=False,
            read_closing_outro=True,
            auto_prefix_chapter_titles=True,
            normalize_chapter_opening_caps=False,
            pronunciation_overrides=[],
            manual_overrides=[],
            heteronym_overrides=[],
            normalization_overrides=None,
            metadata_tags={},
            cover_image_path=None,
            cover_image_mime=None,
            generate_epub3=False,
            is_direct_text=False,
            from_queue=False,
            display_path=None,
            save_base_path=None,
            cancel_requested=False,
        )
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def test_basic_field_mapping(self):
        from abogen.pyqt.conversion_adapter import build_conversion_request_from_thread

        thread = self._make_thread()
        req = build_conversion_request_from_thread(thread)

        assert isinstance(req, ConversionRequest)
        assert req.source_path == Path("/tmp/test.epub")
        assert req.language == "a"
        assert req.voice == "M1"
        assert req.speed == 1.0
        assert req.output_format == "wav"

    def test_direct_text_mode(self):
        from abogen.pyqt.conversion_adapter import build_conversion_request_from_thread

        thread = self._make_thread(
            is_direct_text=True,
            file_name="Hello world",
        )
        req = build_conversion_request_from_thread(thread)

        assert req.source_path is None
        assert req.direct_text == "Hello world"

    def test_from_queue_uses_save_base_path(self):
        from abogen.pyqt.conversion_adapter import build_conversion_request_from_thread

        thread = self._make_thread(
            from_queue=True,
            save_base_path="/queue/book.epub",
            display_path="/display/book.epub",
        )
        req = build_conversion_request_from_thread(thread)

        assert req.original_filename == "book.epub"

    def test_display_path_used_when_not_from_queue(self):
        from abogen.pyqt.conversion_adapter import build_conversion_request_from_thread

        thread = self._make_thread(
            from_queue=False,
            display_path="/display/book.epub",
            save_base_path="/queue/book.epub",
        )
        req = build_conversion_request_from_thread(thread)

        assert req.original_filename == "book.epub"

    def test_output_folder_mapped(self):
        from abogen.pyqt.conversion_adapter import build_conversion_request_from_thread

        thread = self._make_thread(output_folder="/output")
        req = build_conversion_request_from_thread(thread)

        assert req.output_folder == Path("/output")

    def test_none_defaults_handled(self):
        from abogen.pyqt.conversion_adapter import build_conversion_request_from_thread

        thread = self._make_thread(
            lang_code=None,
            voice=None,
            speed=None,
            output_format=None,
            subtitle_mode=None,
            save_option=None,
            silence_duration=None,
            chapter_intro_delay=None,
            supertonic_total_steps=None,
            max_subtitle_words=None,
        )
        req = build_conversion_request_from_thread(thread)

        assert req.language == "a"
        assert req.voice == "M1"
        assert req.speed == 1.0
        assert req.output_format == "wav"
        assert req.subtitle_mode == "Disabled"
        assert req.save_mode == "save_next_to_input"
        assert req.silence_between_chapters == 2.0
        assert req.chapter_intro_delay == 0.0
        assert req.supertonic_total_steps == 5
        assert req.max_subtitle_words == 50

    def test_chapter_chunks_not_mapped(self):
        from abogen.pyqt.conversion_adapter import build_conversion_request_from_thread

        thread = self._make_thread()
        req = build_conversion_request_from_thread(thread)

        assert req.chapter_overrides == []
        assert req.chunks == []
        assert req.chunk_level == "paragraph"
        assert req.speaker_mode == "single"
        assert req.speakers == {}


class TestPyQtEvents:
    """Test PyQt ConversionEvents implementation."""

    def test_log_emits_signal(self):
        from abogen.pyqt.conversion_adapter import PyQtEvents

        thread = SimpleNamespace(
            log_updated=MagicMock(),
        )
        events = PyQtEvents(thread)
        events.log("test message", level="info")

        thread.log_updated.emit.assert_called_once()

    def test_progress_emits_signal(self):
        from abogen.pyqt.conversion_adapter import PyQtEvents

        thread = SimpleNamespace(
            progress_updated=MagicMock(),
        )
        events = PyQtEvents(thread)
        events.progress(50, "2m 30s")

        thread.progress_updated.emit.assert_called_once_with(50, "2m 30s")

    def test_check_cancelled_raises(self):
        from abogen.pyqt.conversion_adapter import ConversionCancelled, PyQtEvents

        thread = SimpleNamespace(cancel_requested=True)
        events = PyQtEvents(thread)

        with pytest.raises(ConversionCancelled):
            events.check_cancelled()

    def test_check_not_cancelled_passes(self):
        from abogen.pyqt.conversion_adapter import PyQtEvents

        thread = SimpleNamespace(cancel_requested=False)
        events = PyQtEvents(thread)

        events.check_cancelled()  # Should not raise


class TestPyQtPipelineProvider:
    """Test PyQt PipelineProvider implementation."""

    def test_get_returns_backend(self):
        from abogen.pyqt.conversion_adapter import PyQtPipelineProvider

        backend = MagicMock()
        provider = PyQtPipelineProvider(backend)

        result = provider.get("kokoro", "a", False)

        assert result is backend

    def test_dispose_all_noop(self):
        from abogen.pyqt.conversion_adapter import PyQtPipelineProvider

        backend = MagicMock()
        provider = PyQtPipelineProvider(backend)

        provider.dispose_all()  # Should not raise


class TestPyQtVoiceResolver:
    """Test PyQt VoiceResolver implementation."""

    def test_resolve_returns_resolved_voice(self):
        from abogen.pyqt.conversion_adapter import PyQtVoiceResolver

        loaded_voice = MagicMock()
        thread = SimpleNamespace(
            load_voice_cached=MagicMock(return_value=loaded_voice),
            backend=MagicMock(),
            speed=1.0,
            supertonic_total_steps=5,
        )
        resolver = PyQtVoiceResolver(thread)
        result = resolver.resolve("M1")

        assert isinstance(result, ResolvedVoice)
        assert result.provider == "kokoro"
        assert result.voice is loaded_voice
        assert result.speed == 1.0
        assert result.supertonic_steps == 5
