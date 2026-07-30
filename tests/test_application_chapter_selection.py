"""Tests for application/chapter_selection.py."""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dataclasses import dataclass
from abogen.application.chapter_selection import build_chapter_payload


@dataclass
class FakeChapter:
    title: str
    text: str


class TestBuildChapterPayload:
    def test_empty_chapters(self):
        result = build_chapter_payload([], source_name="book.txt")
        assert len(result) == 1
        assert result[0]["id"] == "0000"
        assert result[0]["title"] == "book.txt"
        assert result[0]["text"] == ""
        assert result[0]["characters"] == 0
        assert result[0]["enabled"] is True

    def test_single_chapter_always_enabled(self):
        chapters = [FakeChapter("Chapter 1", "Once upon a time.")]
        result = build_chapter_payload(chapters)
        assert len(result) == 1
        assert result[0]["title"] == "Chapter 1"
        assert result[0]["enabled"] is True
        assert result[0]["index"] == 0
        assert result[0]["id"] == "0000"

    def test_content_chapters_preselected(self):
        chapters = [
            FakeChapter("Chapter 1", "The story begins with a long enough text to pass the threshold."),
            FakeChapter("Chapter 2", "The story continues with another substantial chunk of text."),
        ]
        result = build_chapter_payload(chapters)
        assert all(ch["enabled"] for ch in result)

    def test_supplement_not_preselected(self):
        chapters = [
            FakeChapter("Chapter 1", "The story begins with a long enough text to pass the threshold."),
            FakeChapter("Title Page", ""),
            FakeChapter("Copyright", "All rights reserved."),
            FakeChapter("Table of Contents", ""),
            FakeChapter("Chapter 2", "The story continues with another substantial chunk of text."),
        ]
        result = build_chapter_payload(chapters)
        titles_enabled = {ch["title"]: ch["enabled"] for ch in result}
        assert titles_enabled["Chapter 1"] is True
        assert titles_enabled["Chapter 2"] is True
        assert titles_enabled["Title Page"] is False
        assert titles_enabled["Copyright"] is False
        assert titles_enabled["Table of Contents"] is False

    def test_at_least_one_enabled(self):
        chapters = [
            FakeChapter("Title Page", ""),
            FakeChapter("Copyright", "All rights reserved."),
        ]
        result = build_chapter_payload(chapters)
        assert any(ch["enabled"] for ch in result)

    def test_characters_calculated(self):
        chapters = [FakeChapter("Ch1", "Hello world")]
        result = build_chapter_payload(chapters)
        assert result[0]["characters"] == 11

    def test_ids_are_zero_padded(self):
        chapters = [FakeChapter(f"Ch{i}", f"text {i}") for i in range(5)]
        result = build_chapter_payload(chapters)
        ids = [ch["id"] for ch in result]
        assert ids == ["0000", "0001", "0002", "0003", "0004"]

    def test_indices_are_sequential(self):
        chapters = [FakeChapter(f"Ch{i}", f"text {i}") for i in range(3)]
        result = build_chapter_payload(chapters)
        indices = [ch["index"] for ch in result]
        assert indices == [0, 1, 2]

    def test_source_name_used_for_empty(self):
        result = build_chapter_payload([], source_name="mybook.epub")
        assert result[0]["title"] == "mybook.epub"

    def test_default_source_name(self):
        result = build_chapter_payload([])
        assert result[0]["title"] == ""

    def test_none_title_and_text(self):
        class BadChapter:
            def __init__(self):
                self.title = None
                self.text = None

        result = build_chapter_payload([BadChapter()])
        assert result[0]["title"] == ""
        assert result[0]["text"] == ""
        assert result[0]["enabled"] is True  # single chapter always enabled
