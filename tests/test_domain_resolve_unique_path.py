"""Tests for domain/output_paths.py — resolve_unique_path."""

import os
import tempfile

from abogen.domain.output_paths import resolve_unique_path


class TestResolveUniquePath:
    def test_no_collision(self, tmp_path):
        result = resolve_unique_path(str(tmp_path), "chapter", "srt")
        assert result == os.path.join(str(tmp_path), "chapter")
        assert not os.path.exists(result)

    def test_collision_appends_counter(self, tmp_path):
        (tmp_path / "chapter.srt").touch()
        result = resolve_unique_path(str(tmp_path), "chapter", "srt", {"srt"})
        assert result == os.path.join(str(tmp_path), "chapter_2")

    def test_multiple_collisions(self, tmp_path):
        (tmp_path / "chapter.srt").touch()
        (tmp_path / "chapter_2.srt").touch()
        (tmp_path / "chapter_3.srt").touch()
        result = resolve_unique_path(str(tmp_path), "chapter", "srt", {"srt"})
        assert result == os.path.join(str(tmp_path), "chapter_4")

    def test_no_allowed_extensions_skips_files(self, tmp_path):
        (tmp_path / "chapter.txt").touch()
        result = resolve_unique_path(str(tmp_path), "chapter", "srt")
        assert result == os.path.join(str(tmp_path), "chapter")

    def test_sanitizes_name(self, tmp_path):
        # On Windows, ":" is illegal; on Linux it's allowed.
        # Just verify the function doesn't crash and returns a valid path.
        result = resolve_unique_path(str(tmp_path), "My Chapter: Part 1", "srt")
        assert os.path.dirname(result) == str(tmp_path)

    def test_directory_collision(self, tmp_path):
        (tmp_path / "chapter").mkdir()
        result = resolve_unique_path(str(tmp_path), "chapter", "srt")
        assert result == os.path.join(str(tmp_path), "chapter_2")

    def test_case_insensitive_extension(self, tmp_path):
        (tmp_path / "chapter.SRT").touch()
        result = resolve_unique_path(str(tmp_path), "chapter", "srt", {"srt"})
        assert result == os.path.join(str(tmp_path), "chapter_2")

    def test_unrelated_extensions_no_collision(self, tmp_path):
        (tmp_path / "chapter.mp3").touch()
        result = resolve_unique_path(str(tmp_path), "chapter", "srt", {"srt"})
        assert result == os.path.join(str(tmp_path), "chapter")
