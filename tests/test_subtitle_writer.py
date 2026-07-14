"""Tests for infrastructure/subtitle_writer.py — SrtWriter, AssWriter, VttWriter."""
from __future__ import annotations

import pytest
from pathlib import Path

from abogen.infrastructure.subtitle_writer import (
    AssWriter,
    SrtWriter,
    SubtitleAlignment,
    SubtitleConfig,
    SubtitleFormat,
    SubtitleMode,
    VttWriter,
    create_subtitle_writer,
)


# ===================================================================
# SrtWriter._format_time
# ===================================================================

class TestSrtFormatTime:
    def test_zero(self):
        assert SrtWriter._format_time(0.0) == "00:00:00,000"

    def test_simple(self):
        assert SrtWriter._format_time(61.5) == "00:01:01,500"

    def test_hours(self):
        assert SrtWriter._format_time(3661.123) == "01:01:01,123"

    def test_large(self):
        assert SrtWriter._format_time(7384.0) == "02:03:04,000"

    def test_fractional_seconds(self):
        assert SrtWriter._format_time(0.999) == "00:00:00,999"

    def test_matches_old_format_timestamp(self):
        """Verify matches old _format_timestamp(ass=False) from conversion_runner."""
        import math
        for t in [0.0, 61.5, 3661.123, 7384.0, 0.999, 125.7]:
            h = int(t // 3600)
            m = int((t % 3600) // 60)
            s = int(t % 60)
            ms = int((t - math.floor(t)) * 1000)
            expected = f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
            assert SrtWriter._format_time(t) == expected, f"Mismatch at t={t}"


# ===================================================================
# AssWriter._format_time
# ===================================================================

class TestAssFormatTime:
    def test_zero(self):
        assert AssWriter._format_time(0.0) == "0:00:00.00"

    def test_simple(self):
        assert AssWriter._format_time(61.5) == "0:01:01.50"

    def test_hours(self):
        assert AssWriter._format_time(3661.12) == "1:01:01.12"

    def test_centiseconds(self):
        assert AssWriter._format_time(1.55) == "0:00:01.55"

    def test_matches_old_format_timestamp_ass(self):
        """Verify matches old _format_timestamp(ass=True) from conversion_runner.

        Note: the old code used int(milliseconds/10) which truncates centiseconds,
        while the new code uses float formatting which rounds. For most values they
        match; the difference is at most 1 centisecond due to float precision.
        """
        import math
        for t in [0.0, 61.5, 1.55, 125.7]:
            h = int(t // 3600)
            m = int((t % 3600) // 60)
            s = int(t % 60)
            ms = int((t - math.floor(t)) * 1000)
            cs = int(ms / 10)
            expected = f"{h:01d}:{m:02d}:{s:02d}.{cs:02d}"
            assert AssWriter._format_time(t) == expected, f"Mismatch at t={t}"


# ===================================================================
# SrtWriter full write
# ===================================================================

class TestSrtWriter:
    def test_single_entry(self, tmp_path):
        path = tmp_path / "test.srt"
        writer = SrtWriter(path, SubtitleConfig(format=SubtitleFormat.SRT, mode=SubtitleMode.LINE))
        writer.write_entry(start=0.0, end=2.5, text="Hello")
        writer.close()
        content = path.read_text()
        assert "1\n" in content
        assert "00:00:00,000 --> 00:00:02,500" in content
        assert "Hello\n" in content

    def test_multiple_entries(self, tmp_path):
        path = tmp_path / "test.srt"
        writer = SrtWriter(path, SubtitleConfig(format=SubtitleFormat.SRT, mode=SubtitleMode.LINE))
        writer.write_entry(start=0.0, end=1.0, text="First")
        writer.write_entry(start=1.0, end=2.0, text="Second")
        writer.close()
        content = path.read_text()
        assert "1\n" in content
        assert "2\n" in content
        assert "First" in content
        assert "Second" in content

    def test_voice_prefix(self, tmp_path):
        path = tmp_path / "test.srt"
        writer = SrtWriter(path, SubtitleConfig(format=SubtitleFormat.SRT, mode=SubtitleMode.LINE))
        writer.write_entry(start=0.0, end=1.0, text="Hello", voice="af_heart")
        writer.close()
        content = path.read_text()
        assert "[af_heart] Hello" in content

    def test_auto_index(self, tmp_path):
        path = tmp_path / "test.srt"
        writer = SrtWriter(path, SubtitleConfig(format=SubtitleFormat.SRT, mode=SubtitleMode.LINE))
        writer.write_entry(start=0.0, end=1.0, text="A")
        writer.write_entry(start=1.0, end=2.0, text="B")
        writer.write_entry(start=2.0, end=3.0, text="C")
        writer.close()
        content = path.read_text()
        assert "1\n" in content
        assert "2\n" in content
        assert "3\n" in content


# ===================================================================
# AssWriter full write
# ===================================================================

class TestAssWriter:
    def test_header_structure(self, tmp_path):
        path = tmp_path / "test.ass"
        writer = AssWriter(path, SubtitleConfig(format=SubtitleFormat.ASS, mode=SubtitleMode.LINE))
        writer.open()
        writer.close()
        content = path.read_text()
        assert "[Script Info]" in content
        assert "[V4+ Styles]" in content
        assert "[Events]" in content
        assert "Format: Layer, Start, End" in content

    def test_single_entry(self, tmp_path):
        path = tmp_path / "test.ass"
        writer = AssWriter(path, SubtitleConfig(format=SubtitleFormat.ASS, mode=SubtitleMode.LINE))
        writer.write_entry(start=0.0, end=2.5, text="Hello")
        writer.close()
        content = path.read_text()
        assert "Dialogue:" in content
        assert "Hello" in content

    def test_voice_prefix(self, tmp_path):
        path = tmp_path / "test.ass"
        writer = AssWriter(path, SubtitleConfig(format=SubtitleFormat.ASS, mode=SubtitleMode.LINE))
        writer.write_entry(start=0.0, end=1.0, text="Hello", voice="af_heart")
        writer.close()
        content = path.read_text()
        assert "[af_heart] Hello" in content

    def test_highlight_mode(self, tmp_path):
        path = tmp_path / "test.ass"
        config = SubtitleConfig(
            format=SubtitleFormat.ASS,
            mode=SubtitleMode.SENTENCE_HIGHLIGHT,
        )
        writer = AssWriter(path, config)
        writer.write_entry(start=0.0, end=1.0, text="Hello world")
        writer.close()
        content = path.read_text()
        assert "Highlight" in content
        assert r"{\k100}" in content

    def test_centered_alignment(self, tmp_path):
        path = tmp_path / "test.ass"
        config = SubtitleConfig(
            format=SubtitleFormat.ASS,
            mode=SubtitleMode.LINE,
            alignment=SubtitleAlignment.CENTER,
        )
        writer = AssWriter(path, config)
        writer.open()
        writer.close()
        content = path.read_text()
        # Centered uses alignment=5
        assert ",5," in content or ",5\n" in content


# ===================================================================
# VttWriter
# ===================================================================

class TestVttWriter:
    def test_header(self, tmp_path):
        path = tmp_path / "test.vtt"
        writer = VttWriter(path, SubtitleConfig(format=SubtitleFormat.VTT, mode=SubtitleMode.LINE))
        writer.open()
        writer.close()
        content = path.read_text()
        assert content.startswith("WEBVTT")

    def test_single_entry(self, tmp_path):
        path = tmp_path / "test.vtt"
        writer = VttWriter(path, SubtitleConfig(format=SubtitleFormat.VTT, mode=SubtitleMode.LINE))
        writer.write_entry(start=0.0, end=2.5, text="Hello")
        writer.close()
        content = path.read_text()
        assert "1\n" in content
        assert "Hello" in content


# ===================================================================
# create_subtitle_writer factory
# ===================================================================

class TestCreateSubtitleWriter:
    def test_srt(self, tmp_path):
        path = tmp_path / "test.srt"
        writer = create_subtitle_writer(path, "srt", "Line")
        assert isinstance(writer, SrtWriter)
        writer.close()

    def test_ass(self, tmp_path):
        path = tmp_path / "test.ass"
        writer = create_subtitle_writer(path, "ass", "Line")
        assert isinstance(writer, AssWriter)
        writer.close()

    def test_vtt(self, tmp_path):
        path = tmp_path / "test.vtt"
        writer = create_subtitle_writer(path, "vtt", "Line")
        assert isinstance(writer, VttWriter)
        writer.close()

    def test_unsupported_raises(self, tmp_path):
        path = tmp_path / "test.xyz"
        with pytest.raises(ValueError):
            create_subtitle_writer(path, "xyz", "Line")


# ===================================================================
# Context manager
# ===================================================================

class TestContextManager:
    def test_srt_context_manager(self, tmp_path):
        path = tmp_path / "test.srt"
        with SrtWriter(path, SubtitleConfig(format=SubtitleFormat.SRT, mode=SubtitleMode.LINE)) as writer:
            writer.write_entry(start=0.0, end=1.0, text="Hello")
        content = path.read_text()
        assert "Hello" in content

    def test_ass_context_manager(self, tmp_path):
        path = tmp_path / "test.ass"
        with AssWriter(path, SubtitleConfig(format=SubtitleFormat.ASS, mode=SubtitleMode.LINE)) as writer:
            writer.write_entry(start=0.0, end=1.0, text="Hello")
        content = path.read_text()
        assert "Dialogue:" in content
