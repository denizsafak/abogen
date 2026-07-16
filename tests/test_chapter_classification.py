"""Tests for domain/chapter_classification.py."""

from abogen.domain.chapter_classification import (
    supplement_score,
    should_preselect_chapter,
    ensure_at_least_one_chapter_enabled,
)


class TestSupplementScore:
    def test_title_page_high_score(self):
        score = supplement_score("Title Page", "", 0)
        assert score > 3.0

    def test_chapter_title_negative_score(self):
        score = supplement_score("Chapter 1", "", 0)
        assert score < 0

    def test_copyright_high_score(self):
        score = supplement_score("Copyright", "All rights reserved.", 0)
        assert score > 2.0

    def test_short_text_adds_score(self):
        score = supplement_score("Some Title", "Short text.", 0)
        assert score > 0.5

    def test_long_text_low_score_contribution(self):
        score = supplement_score("Some Title", "word " * 200, 0)
        assert score < 0.5

    def test_index_zero_bonus(self):
        score_title = supplement_score("Dedication", "For my family.", 0)
        score_other = supplement_score("Dedication", "For my family.", 3)
        assert score_title > score_other

    def test_empty_title_and_text(self):
        score = supplement_score("", "", 5)
        assert score == 0.9  # short text bonus only (len("") ≤ 150)

    def test_newsletter_keyword_high_score(self):
        score = supplement_score("Subscribe", "Join our newsletter today", 0)
        assert score > 3.0

    def test_acknowledgments_pattern(self):
        score = supplement_score("Acknowledgements", "", 0)
        assert score > 2.0

    def test_glossary_in_title(self):
        score = supplement_score("Glossary", "", 0)
        assert score > 2.0


class TestShouldPreselectChapter:
    def test_single_chapter_always_preselected(self):
        assert should_preselect_chapter("Anything", "", 0, 1) is True

    def test_chapter_preselected_when_low_score(self):
        assert should_preselect_chapter("Chapter 1", "The story begins.", 0, 10) is True

    def test_title_page_not_preselected(self):
        assert should_preselect_chapter("Title Page", "", 0, 10) is False

    def test_copyright_not_preselected(self):
        assert should_preselect_chapter("Copyright", "All rights reserved.", 0, 10) is False

    def test_toc_not_preselected(self):
        assert should_preselect_chapter("Table of Contents", "", 0, 10) is False


class TestEnsureAtLeastOneChapterEnabled:
    def test_empty_list(self):
        chapters = []
        ensure_at_least_one_chapter_enabled(chapters)
        assert chapters == []

    def test_already_has_enabled(self):
        chapters = [
            {"title": "Ch1", "enabled": False},
            {"title": "Ch2", "enabled": True},
        ]
        ensure_at_least_one_chapter_enabled(chapters)
        assert chapters[1]["enabled"] is True
        assert chapters[0]["enabled"] is False

    def test_none_enabled_picks_longest(self):
        chapters = [
            {"title": "Ch1", "enabled": False, "characters": 100},
            {"title": "Ch2", "enabled": False, "characters": 500},
            {"title": "Ch3", "enabled": False, "characters": 200},
        ]
        ensure_at_least_one_chapter_enabled(chapters)
        assert chapters[1]["enabled"] is True

    def test_single_chapter_gets_enabled(self):
        chapters = [{"title": "Only", "enabled": False}]
        ensure_at_least_one_chapter_enabled(chapters)
        assert chapters[0]["enabled"] is True
