"""Tests for ExportService FFmpeg metadata methods."""
import os
import shutil
import subprocess
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


class TestEmbedM4bCoverInputIndex:
    """embed_m4b_metadata must map the cover from its real FFmpeg input index.

    Inputs are: 0 = audio, then the optional ffmetadata file, then the
    optional cover. The cover is input 2 when chapter/metadata ffmetadata is
    present and input 1 when it is not. Hardcoding ``1:v:0`` made FFmpeg look
    for a video stream in the ffmetadata input and fail (exit 234).
    """

    CHAPTERS = [
        {"title": "Opening", "start": 0.0, "end": 0.5},
        {"title": "Closing", "start": 0.5, "end": 1.0},
    ]

    def _run(self, tmp_path, *, with_ffmetadata, with_cover, cover_exists=True):
        audio = tmp_path / "book.m4b"
        audio.write_bytes(b"audio")
        cover = tmp_path / "cover.png"
        if with_cover and cover_exists:
            cover.write_bytes(b"png")
        captured = {}

        class _Proc:
            def wait(self):
                return 0

        def fake_create_process(cmd, text=True):
            captured["cmd"] = list(cmd)
            Path(cmd[-1]).write_bytes(b"muxed")
            return _Proc()

        metadata = {"title": "Book"} if with_ffmetadata else {}
        chapters = self.CHAPTERS if with_ffmetadata else []
        with patch("abogen.infrastructure.exporters.create_process", fake_create_process), \
                patch.object(ExportService, "_apply_m4b_chapters_mutagen"), \
                patch.object(ExportService, "_write_m4b_freeform_tags"):
            ExportService().embed_m4b_metadata(
                audio, metadata, chapters,
                cover_path=cover if with_cover else None,
                cover_mime="image/png" if with_cover else None,
            )
        return captured["cmd"]

    @staticmethod
    def _inputs(cmd):
        return [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-i"]

    @staticmethod
    def _maps(cmd):
        return [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-map"]

    def test_cover_with_ffmetadata_maps_input_2(self, tmp_path):
        cmd = self._run(tmp_path, with_ffmetadata=True, with_cover=True)
        inputs = self._inputs(cmd)
        assert len(inputs) == 3
        assert inputs[1].endswith(".ffmeta")
        assert inputs[2].endswith("cover.png")
        assert self._maps(cmd) == ["0:a", "2:v:0"]
        assert cmd[cmd.index("-map_metadata") + 1] == "1"
        assert cmd[cmd.index("-map_chapters") + 1] == "1"
        assert cmd[cmd.index("-disposition:v:0") + 1] == "attached_pic"
        # use_metadata_tags makes the mp4 muxer drop the attached picture.
        assert cmd[cmd.index("-movflags") + 1] == "+faststart"

    def test_cover_without_ffmetadata_maps_input_1(self, tmp_path):
        cmd = self._run(tmp_path, with_ffmetadata=False, with_cover=True)
        inputs = self._inputs(cmd)
        assert len(inputs) == 2
        assert inputs[1].endswith("cover.png")
        assert self._maps(cmd) == ["0:a", "1:v:0"]
        assert cmd[cmd.index("-map_metadata") + 1] == "0"
        assert "-map_chapters" not in cmd
        assert cmd[cmd.index("-movflags") + 1] == "+faststart"

    def test_ffmetadata_without_cover_maps_audio_only(self, tmp_path):
        cmd = self._run(tmp_path, with_ffmetadata=True, with_cover=False)
        assert len(self._inputs(cmd)) == 2
        assert self._maps(cmd) == ["0:a"]
        assert cmd[cmd.index("-map_metadata") + 1] == "1"
        assert cmd[cmd.index("-map_chapters") + 1] == "1"
        assert "-disposition:v:0" not in cmd
        assert cmd[cmd.index("-movflags") + 1] == "+faststart+use_metadata_tags"

    def test_no_ffmetadata_no_cover_maps_audio_only(self, tmp_path):
        cmd = self._run(tmp_path, with_ffmetadata=False, with_cover=False)
        assert len(self._inputs(cmd)) == 1
        assert self._maps(cmd) == ["0:a"]
        assert cmd[cmd.index("-map_metadata") + 1] == "0"

    def test_nonexistent_cover_is_skipped(self, tmp_path):
        cmd = self._run(tmp_path, with_ffmetadata=True, with_cover=True, cover_exists=False)
        assert len(self._inputs(cmd)) == 2
        assert self._maps(cmd) == ["0:a"]
        assert "-disposition:v:0" not in cmd


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="real ffmpeg not on PATH")
class TestEmbedM4bCoverRealFfmpeg:
    """Real FFmpeg mux through ExportService.embed_m4b_metadata (no argv mocks).

    Only static_ffmpeg.add_paths is stubbed (tests/__init__.py and below) so
    the already-installed ffmpeg on PATH is used and nothing is downloaded.
    """

    CHAPTERS = TestEmbedM4bCoverInputIndex.CHAPTERS

    @staticmethod
    def _ffmpeg(*args):
        return subprocess.run(["ffmpeg", "-v", "error", "-y", *args], capture_output=True, text=True)

    def _fixture(self, tmp_path):
        audio = tmp_path / "book.m4b"
        cover = tmp_path / "cover.png"
        made = self._ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                            "-c:a", "aac", "-b:a", "64k", "-f", "mp4", str(audio))
        assert made.returncode == 0, made.stderr
        made = self._ffmpeg("-f", "lavfi", "-i", "color=c=red:s=32x32", "-frames:v", "1", str(cover))
        assert made.returncode == 0, made.stderr
        return audio, cover

    def test_cover_and_chapters_mux_into_playable_m4b(self, tmp_path, monkeypatch):
        monkeypatch.setattr("abogen.infrastructure.exporters.static_ffmpeg.add_paths", lambda *a, **k: None)
        audio, cover = self._fixture(tmp_path)

        ExportService().embed_m4b_metadata(
            audio, {"title": "Cover Test", "artist": "Abogen"}, self.CHAPTERS,
            cover_path=cover, cover_mime="image/png",
        )

        # Whole file decodes, and the audio still lasts about one second.
        decoded = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(audio), "-map", "0:a", "-f", "s16le", "-ac", "1", "-ar", "8000", "-"],
            capture_output=True,
        )
        assert decoded.returncode == 0, decoded.stderr
        assert 0.9 <= len(decoded.stdout) / 2 / 8000 <= 1.2

        # Chapter titles and timings survive.
        meta = tmp_path / "out.ffmeta"
        dumped = self._ffmpeg("-i", str(audio), "-f", "ffmetadata", str(meta))
        assert dumped.returncode == 0, dumped.stderr
        text = meta.read_text(encoding="utf-8")
        assert "title=Opening" in text and "title=Closing" in text
        assert "title=Cover Test" in text
        spans = []
        for block in text.split("[CHAPTER]")[1:]:
            fields = dict(line.split("=", 1) for line in block.strip().splitlines())
            num, den = (int(x) for x in fields["TIMEBASE"].split("/"))
            spans.append((fields["title"], int(fields["START"]) * num / den, int(fields["END"]) * num / den))
        assert [title for title, _, _ in spans] == ["Opening", "Closing"]
        assert [(round(s, 2), round(e, 2)) for _, s, e in spans] == [(0.0, 0.5), (0.5, 1.0)]

        self._assert_cover(audio, tmp_path)

    def test_cover_without_chapter_metadata_is_kept(self, tmp_path, monkeypatch):
        monkeypatch.setattr("abogen.infrastructure.exporters.static_ffmpeg.add_paths", lambda *a, **k: None)
        audio, cover = self._fixture(tmp_path)

        ExportService().embed_m4b_metadata(audio, {}, [], cover_path=cover, cover_mime="image/png")

        decoded = self._ffmpeg("-i", str(audio), "-f", "null", "-")
        assert decoded.returncode == 0, decoded.stderr
        self._assert_cover(audio, tmp_path)

    RICH_METADATA = {
        "title": "Café — 東京 Story",
        "artist": "Zoë Author",
        "album": "Ålbum Name",
        "genre": "Audiobook",
        "year": 2026,
        "narrator": "Narrátor 声",
        "series": "Série Name",
        "series_part": 3,
        "empty_key": "",
        "none_key": None,
    }

    def _mux_rich(self, tmp_path, monkeypatch, with_cover):
        monkeypatch.setattr("abogen.infrastructure.exporters.static_ffmpeg.add_paths", lambda *a, **k: None)
        audio, cover = self._fixture(tmp_path)
        ExportService().embed_m4b_metadata(
            audio, dict(self.RICH_METADATA), self.CHAPTERS,
            cover_path=cover if with_cover else None, cover_mime="image/png" if with_cover else None,
        )
        return audio

    def _assert_audio_and_chapters(self, audio, tmp_path):
        decoded = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(audio), "-map", "0:a", "-f", "s16le", "-ac", "1", "-ar", "8000", "-"],
            capture_output=True,
        )
        assert decoded.returncode == 0, decoded.stderr
        assert 0.9 <= len(decoded.stdout) / 2 / 8000 <= 1.2
        meta = tmp_path / "rich.ffmeta"
        dumped = self._ffmpeg("-i", str(audio), "-f", "ffmetadata", str(meta))
        assert dumped.returncode == 0, dumped.stderr
        text = meta.read_text(encoding="utf-8")
        assert text.count("[CHAPTER]") == 2
        assert "title=Opening" in text and "title=Closing" in text
        return text

    def test_cover_export_preserves_custom_metadata(self, tmp_path, monkeypatch):
        audio = self._mux_rich(tmp_path, monkeypatch, with_cover=True)
        text = self._assert_audio_and_chapters(audio, tmp_path)
        for line in ("title=Café — 東京 Story", "artist=Zoë Author", "album=Ålbum Name",
                     "genre=Audiobook", "date=2026", "narrator=Narrátor 声", "series=Série Name",
                     "series_part=3", "year=2026"):
            assert line in text, (line, text)
        self._assert_cover(audio, tmp_path)

        from mutagen.mp4 import MP4
        tags = MP4(str(audio)).tags
        # Standard atoms.
        assert tags["\xa9nam"] == ["Café — 東京 Story"]
        assert tags["\xa9ART"] == ["Zoë Author"]
        assert tags["\xa9alb"] == ["Ålbum Name"]
        assert tags["\xa9gen"] == ["Audiobook"]
        assert tags["\xa9day"] == ["2026"]
        # Every non-empty key is also a freeform tag, coerced with str().
        freeform = {
            key.split(":", 2)[2]: bytes(values[0]).decode("utf-8")
            for key, values in tags.items() if key.startswith("----:com.apple.iTunes:")
        }
        assert freeform == {
            key: str(value) for key, value in self.RICH_METADATA.items() if value not in (None, "")
        }

    def test_no_cover_export_keeps_metadata_tags_path(self, tmp_path, monkeypatch):
        audio = self._mux_rich(tmp_path, monkeypatch, with_cover=False)
        text = self._assert_audio_and_chapters(audio, tmp_path)
        # Unchanged path: use_metadata_tags stores every key as an mdta tag.
        for line in ("narrator=Narrátor 声", "series=Série Name", "series_part=3", "year=2026",
                     "title=Café — 東京 Story", "artist=Zoë Author", "album=Ålbum Name", "genre=Audiobook"):
            assert line in text, (line, text)
        from mutagen.mp4 import MP4
        assert not any(k.startswith("----:") for k in (MP4(str(audio)).tags or {}))

    def _assert_cover(self, audio, tmp_path):
        # The cover is an attached-picture stream and a real JPEG covr atom.
        from mutagen.mp4 import MP4
        covr = MP4(str(audio)).tags["covr"]
        assert len(covr) == 1 and bytes(covr[0]).startswith(b"\xff\xd8")
        extracted = tmp_path / "extracted.jpg"
        pulled = self._ffmpeg("-i", str(audio), "-map", "0:v:0", "-c", "copy", "-f", "mjpeg", str(extracted))
        assert pulled.returncode == 0, pulled.stderr
        assert extracted.read_bytes() == bytes(covr[0])
        frame = self._ffmpeg("-i", str(extracted), "-f", "null", "-")
        assert frame.returncode == 0, frame.stderr
