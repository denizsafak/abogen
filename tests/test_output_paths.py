"""Tests for output path utilities.

Tests import from domain/output_paths.py (new module).
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest


# ---------------------------------------------------------------------------
# slugify
# ---------------------------------------------------------------------------


class TestSlugify:
    """slugify converts title to filesystem-safe slug."""

    def test_basic_slug(self):
        from abogen.domain.output_paths import slugify

        assert slugify("Hello World", 0) == "hello_world"

    def test_strips_special_chars(self):
        from abogen.domain.output_paths import slugify

        result = slugify("Chapter 1: The Beginning!", 0)
        assert result == "chapter_1_the_beginning"

    def test_empty_title_uses_index(self):
        from abogen.domain.output_paths import slugify

        assert slugify("", 5) == "chapter_05"

    def test_truncated_at_80(self):
        from abogen.domain.output_paths import slugify

        long_title = "a" * 100
        assert len(slugify(long_title, 0)) == 80

    def test_preserves_hyphens(self):
        from abogen.domain.output_paths import slugify

        assert slugify("mid-night", 0) == "mid-night"


# ---------------------------------------------------------------------------
# sanitize_output_stem
# ---------------------------------------------------------------------------


class TestSanitizeOutputStem:
    """sanitize_output_stem cleans filename stem."""

    def test_basic_sanitize(self):
        from abogen.domain.output_paths import sanitize_output_stem

        assert sanitize_output_stem("my file.mp3") == "my_file"

    def test_empty_returns_default(self):
        from abogen.domain.output_paths import sanitize_output_stem

        assert sanitize_output_stem("") == "output"

    def test_strips_underscores(self):
        from abogen.domain.output_paths import sanitize_output_stem

        assert sanitize_output_stem("__test__") == "test"


# ---------------------------------------------------------------------------
# output_timestamp_token
# ---------------------------------------------------------------------------


class TestOutputTimestampToken:
    """output_timestamp_token returns timestamp string."""

    def test_format(self):
        from abogen.domain.output_paths import output_timestamp_token

        token = output_timestamp_token()
        assert re.match(r"\d{8}-\d{6}", token)


# ---------------------------------------------------------------------------
# build_output_path
# ---------------------------------------------------------------------------


class TestBuildOutputPath:
    """build_output_path builds the output file path."""

    def test_basic_path(self, tmp_path):
        from abogen.domain.output_paths import build_output_path

        result = build_output_path(tmp_path, "test.mp3", "mp3")
        assert result.suffix == ".mp3"
        assert result.parent == tmp_path

    def test_stem_sanitized(self, tmp_path):
        from abogen.domain.output_paths import build_output_path

        result = build_output_path(tmp_path, "my file.txt", "wav")
        assert "my_file" in result.name


# ---------------------------------------------------------------------------
# apply_newline_policy
# ---------------------------------------------------------------------------


class TestApplyNewlinePolicy:
    """apply_newline_policy replaces single newlines in chapter text."""

    def test_noop_when_disabled(self):
        from abogen.domain.output_paths import apply_newline_policy

        from abogen.text_extractor import ExtractedChapter
        chapters = [ExtractedChapter(title="t", text="a\nb")]
        apply_newline_policy(chapters, False)
        assert chapters[0].text == "a\nb"

    def test_replaces_single_newlines(self):
        from abogen.domain.output_paths import apply_newline_policy

        from abogen.text_extractor import ExtractedChapter
        chapters = [ExtractedChapter(title="t", text="a\nb\nc")]
        apply_newline_policy(chapters, True)
        assert chapters[0].text == "a b c"

    def test_preserves_double_newlines(self):
        from abogen.domain.output_paths import apply_newline_policy

        from abogen.text_extractor import ExtractedChapter
        chapters = [ExtractedChapter(title="t", text="a\n\nb")]
        apply_newline_policy(chapters, True)
        assert chapters[0].text == "a\n\nb"


# ---------------------------------------------------------------------------
# resolve_output_directory
# ---------------------------------------------------------------------------


class TestResolveOutputDirectory:
    """resolve_output_directory determines output dir from save_mode."""

    def test_save_to_desktop(self, tmp_path):
        from abogen.domain.output_paths import resolve_output_directory

        result = resolve_output_directory(
            save_mode="Save to Desktop",
            stored_path=Path("/input/book.epub"),
            output_folder=None,
            desktop_dir=tmp_path,
            user_output_path=None,
            user_cache_outputs=None,
        )
        assert result == tmp_path

    def test_save_next_to_input(self, tmp_path):
        from abogen.domain.output_paths import resolve_output_directory

        stored = tmp_path / "book.epub"
        result = resolve_output_directory(
            save_mode="Save next to input file",
            stored_path=stored,
            output_folder=None,
            desktop_dir=None,
            user_output_path=None,
            user_cache_outputs=None,
        )
        assert result == tmp_path

    def test_choose_output_folder(self, tmp_path):
        from abogen.domain.output_paths import resolve_output_directory

        custom = tmp_path / "custom"
        result = resolve_output_directory(
            save_mode="Choose output folder",
            stored_path=Path("/x/y.epub"),
            output_folder=str(custom),
            desktop_dir=None,
            user_output_path=None,
            user_cache_outputs=None,
        )
        assert result == custom

    def test_use_default_save_location(self, tmp_path):
        from abogen.domain.output_paths import resolve_output_directory

        result = resolve_output_directory(
            save_mode="Use default save location",
            stored_path=Path("/x/y.epub"),
            output_folder=None,
            desktop_dir=None,
            user_output_path=tmp_path / "default",
            user_cache_outputs=None,
        )
        assert result == tmp_path / "default"

    def test_fallback_to_cache(self, tmp_path):
        from abogen.domain.output_paths import resolve_output_directory

        result = resolve_output_directory(
            save_mode="unknown",
            stored_path=Path("/x/y.epub"),
            output_folder=None,
            desktop_dir=None,
            user_output_path=None,
            user_cache_outputs=tmp_path / "cache",
        )
        assert result == tmp_path / "cache"


# ---------------------------------------------------------------------------
# resolve_project_layout
# ---------------------------------------------------------------------------


class TestResolveProjectLayout:
    """resolve_project_layout computes project folder structure."""

    def test_flat_layout(self, tmp_path):
        from abogen.domain.output_paths import resolve_project_layout

        root, audio, subs, meta = resolve_project_layout(
            original_filename="book.epub",
            save_as_project=False,
            base_dir=tmp_path,
            timestamp_fn=lambda: "20260101-000000",
            sanitize_fn=lambda n, i: "book",
        )
        assert audio == root
        assert subs == root
        assert meta is None

    def test_project_layout(self, tmp_path):
        from abogen.domain.output_paths import resolve_project_layout

        root, audio, subs, meta = resolve_project_layout(
            original_filename="book.epub",
            save_as_project=True,
            base_dir=tmp_path,
            timestamp_fn=lambda: "20260101-000000",
            sanitize_fn=lambda n, i: "book",
        )
        assert root.name == "20260101-000000_book"
        assert audio.name == "audio"
        assert subs.name == "subtitles"
        assert meta.name == "metadata"
