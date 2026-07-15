"""Tests for chapter_overrides, merge_metadata, normalize_for_pipeline.

Tests import from domain modules (new location).
"""

from __future__ import annotations

import pytest
from abogen.text_extractor import ExtractedChapter


# ---------------------------------------------------------------------------
# apply_chapter_overrides
# ---------------------------------------------------------------------------


class TestApplyChapterOverrides:
    """apply_chapter_overrides applies chapter overrides to extracted chapters."""

    def test_empty_overrides(self):
        from abogen.domain.chapter_overrides import apply_chapter_overrides

        result, updates, diags = apply_chapter_overrides([], [])
        assert result == []
        assert updates == {}
        assert diags == []

    def test_basic_override_by_index(self):
        from abogen.domain.chapter_overrides import apply_chapter_overrides

        chapters = [ExtractedChapter(title="Ch1", text="original")]
        overrides = [{"index": 0, "title": "New Title", "text": "new text"}]
        result, updates, diags = apply_chapter_overrides(chapters, overrides)
        assert len(result) == 1
        assert result[0].title == "New Title"
        assert result[0].text == "new text"

    def test_override_by_source_title(self):
        from abogen.domain.chapter_overrides import apply_chapter_overrides

        chapters = [ExtractedChapter(title="Ch1", text="text1")]
        overrides = [{"source_title": "Ch1", "title": "Renamed"}]
        result, _, _ = apply_chapter_overrides(chapters, overrides)
        assert result[0].title == "Renamed"

    def test_disabled_override_skipped(self):
        from abogen.domain.chapter_overrides import apply_chapter_overrides

        chapters = [ExtractedChapter(title="Ch1", text="text1")]
        overrides = [{"index": 0, "enabled": False}]
        result, _, _ = apply_chapter_overrides(chapters, overrides)
        assert len(result) == 0

    def test_metadata_updates_collected(self):
        from abogen.domain.chapter_overrides import apply_chapter_overrides

        chapters = [ExtractedChapter(title="Ch1", text="text1")]
        overrides = [{"index": 0, "metadata": {"album": "New Album"}}]
        _, updates, _ = apply_chapter_overrides(chapters, overrides)
        assert updates["album"] == "New Album"

    def test_no_matching_chapter_diagnostic(self):
        from abogen.domain.chapter_overrides import apply_chapter_overrides

        overrides = [{"index": 99, "title": "X"}]
        _, _, diags = apply_chapter_overrides([], overrides)
        assert len(diags) == 1
        assert "Skipped" in diags[0]

    def test_non_dict_override_skipped(self):
        from abogen.domain.chapter_overrides import apply_chapter_overrides

        _, _, diags = apply_chapter_overrides([], ["bad"])
        assert len(diags) == 1

    def test_text_from_base_when_not_provided(self):
        from abogen.domain.chapter_overrides import apply_chapter_overrides

        chapters = [ExtractedChapter(title="Ch1", text="original text")]
        overrides = [{"index": 0, "title": "New Title"}]
        result, _, _ = apply_chapter_overrides(chapters, overrides)
        assert result[0].text == "original text"

    def test_default_title_when_no_base(self):
        from abogen.domain.chapter_overrides import apply_chapter_overrides

        overrides = [{"text": "some text"}]
        result, _, _ = apply_chapter_overrides([], overrides)
        assert result[0].title == "Chapter 1"


# ---------------------------------------------------------------------------
# merge_metadata
# ---------------------------------------------------------------------------


class TestMergeMetadata:
    """merge_metadata merges extracted metadata with overrides."""

    def test_both_empty(self):
        from abogen.domain.metadata_merge import merge_metadata

        assert merge_metadata({}, {}) == {}

    def test_only_extracted(self):
        from abogen.domain.metadata_merge import merge_metadata

        result = merge_metadata({"album": "Book"}, {})
        assert result == {"album": "Book"}

    def test_only_overrides(self):
        from abogen.domain.metadata_merge import merge_metadata

        result = merge_metadata(None, {"album": "Override"})
        assert result == {"album": "Override"}

    def test_override_wins(self):
        from abogen.domain.metadata_merge import merge_metadata

        result = merge_metadata({"album": "Old"}, {"album": "New"})
        assert result == {"album": "New"}

    def test_none_value_deletes_key(self):
        from abogen.domain.metadata_merge import merge_metadata

        result = merge_metadata({"album": "Book"}, {"album": None})
        assert "album" not in result

    def test_none_values_in_extracted_skipped(self):
        from abogen.domain.metadata_merge import merge_metadata

        result = merge_metadata({"album": None, "artist": "X"}, {})
        assert result == {"artist": "X"}

    def test_numeric_values_stringified(self):
        from abogen.domain.metadata_merge import merge_metadata

        result = merge_metadata({"track": 1}, {})
        assert result["track"] == "1"


# ---------------------------------------------------------------------------
# normalize_for_pipeline (thin wrapper)
# ---------------------------------------------------------------------------


class TestNormalizeForPipeline:
    """normalize_for_pipeline normalizes text with runtime settings."""

    def test_basic_normalize(self):
        from abogen.domain.normalization import normalize_text_for_pipeline

        result = normalize_text_for_pipeline("Hello   World")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_empty_string(self):
        from abogen.domain.normalization import normalize_text_for_pipeline

        result = normalize_text_for_pipeline("")
        assert result == ""

    def test_with_overrides(self):
        from abogen.domain.normalization import normalize_text_for_pipeline

        result = normalize_text_for_pipeline("test", normalization_overrides={"number_format": "words"})
        assert isinstance(result, str)
