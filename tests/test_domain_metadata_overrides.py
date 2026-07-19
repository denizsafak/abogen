"""Tests for domain/metadata_overrides.py and webui/services/settings_service.py."""

import pytest

from abogen.domain.metadata_overrides import normalize_opds_metadata


class TestNormalizeOpdsMetadata:
    def test_series_mapping(self):
        result = normalize_opds_metadata({"series": "My Series", "series_index": 3})
        assert result["series"] == "My Series"
        assert result["series_name"] == "My Series"
        assert result["series_index"] == "3"
        assert result["series_position"] == "3"

    def test_series_name_alias(self):
        result = normalize_opds_metadata({"series_name": "Alt Series"})
        assert result["series"] == "Alt Series"
        assert result["series_name"] == "Alt Series"

    def test_tags_to_keywords(self):
        result = normalize_opds_metadata({"tags": "sci-fi, action"})
        assert result["tags"] == "sci-fi, action"
        assert result["keywords"] == "sci-fi, action"
        assert result["genre"] == "sci-fi, action"

    def test_description_summary(self):
        result = normalize_opds_metadata({"description": "A great book"})
        assert result["description"] == "A great book"
        assert result["summary"] == "A great book"

    def test_authors_creator(self):
        result = normalize_opds_metadata({"creator": "Author Name"})
        assert result["authors"] == "Author Name"
        assert result["author"] == "Author Name"

    def test_subtitle_aliases(self):
        result = normalize_opds_metadata({"calibre_subtitle": "Sub Title"})
        assert result["subtitle"] == "Sub Title"

    def test_empty_payload(self):
        result = normalize_opds_metadata({})
        assert result == {}

    def test_list_authors(self):
        result = normalize_opds_metadata({"authors": ["Alice", "Bob"]})
        assert result["authors"] == "Alice, Bob"

    def test_none_values_filtered(self):
        result = normalize_opds_metadata({"series": None, "tags": ""})
        assert "series" not in result
        assert "tags" not in result
